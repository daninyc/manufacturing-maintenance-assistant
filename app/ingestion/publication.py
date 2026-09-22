"""受控发布：同一文件快照用于解析与散列，分块继承内容及权限版本。

先 indexing、再写向量、复核后 active；通过状态与版本屏障隔离半成品和旧块。
SQLite 与 Chroma 不构成一个原子事务，失败时不能放开读取。
"""
import hashlib
from pathlib import Path

from app.ingestion.loaders import load_documents
from app.ingestion.splitter import split_text
from app.security.authorization import ResourcePolicy, can_manage
from app.security.policies import PolicyConflict


def publish_document(path: Path, proposed: ResourcePolicy, store, policies, sessions,
                     token: str, *, expected_version: int, equipment_id: str = ""):
    actor = sessions.authenticate(token)
    if not can_manage(actor):
        raise PermissionError("Management permission required")
    path = Path(path)
    with path.open("rb") as source:
        content = source.read(10 * 1024 * 1024 + 1)
    if len(content) > 10 * 1024 * 1024:
        raise ValueError("Document exceeds 10 MiB")
    pages = load_documents(path, document_id=proposed.resource_id,
                           version=proposed.content_version, equipment_id=equipment_id,
                           content=content, max_pages=200)
    content_hash = hashlib.sha256(content).hexdigest()
    # The effective version is the content digest, not a client assertion.
    pending = ResourcePolicy.model_validate(proposed.model_dump() | {
        "content_version": content_hash, "status": "indexing",
        "policy_version": expected_version + 1})
    policies.save(pending, expected_version=expected_version, actor_id=actor.user_id,
                  actor_token=token)
    active = ResourcePolicy.model_validate(pending.model_dump() | {
        "status": "active", "policy_version": pending.policy_version + 1})
    ids, texts, metadata = [], [], []
    for page in pages:
        prefix = f"{active.resource_id}::{content_hash}::page-{page.metadata['page']}"
        for chunk in split_text(page.text, prefix):
            ids.append(chunk.chunk_id)
            texts.append(chunk.text)
            metadata.append(page.metadata | {
                "chunk_id": chunk.chunk_id, "content_version": content_hash,
                "policy_version": active.policy_version,
                "department_id": active.department_id,
                "classification": active.classification,
                "visibility": active.visibility,
            })
    try:
        store.upsert(ids=ids, documents=texts, metadatas=metadata)
        # Recheck management identity after potentially slow indexing.
        if sessions.authenticate(token) != actor:
            raise PermissionError("Management identity changed")
        policies.save(active, expected_version=pending.policy_version, actor_id=actor.user_id,
                      actor_token=token)
    except Exception:
        failed = ResourcePolicy.model_validate(active.model_dump() | {"status": "failed"})
        try:
            # Trusted failure cleanup may only close this pending version, never activate it.
            policies.save(failed, expected_version=pending.policy_version, actor_id=actor.user_id)
        except PolicyConflict:
            pass  # A newer administrative policy must never be overwritten.
        raise
    return active
