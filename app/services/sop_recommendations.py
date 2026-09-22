"""Server-reviewed simulation SOP rule; arbitrary retrieved text cannot define actions."""
import hashlib

from app.core.config import PROJECT_ROOT
from app.schemas.diagnosis import Evidence, Recommendation
from app.security.authorization import can_read, permitted_chunk


def escalation_recommendation(store, user, policies, symptom):
    # Only explicit conditions present in this reviewed SOP are supported here.
    # Unknown alarms need a code catalog and are not guessed by substring rules.
    matches = [term for term in ("润滑扭矩", "维修过程") if term in symptom]
    if not matches:
        return [], []
    document_id = "SOP-ESCALATION"
    policy = policies.get(document_id)
    if not can_read(user, policy):
        return [], []
    source = PROJECT_ROOT / "data/raw_docs/sops/escalation.txt"
    approved_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    if policy.content_version != approved_hash:
        return [], []  # Updated SOP requires a new reviewed rule, never auto-trust it.
    condition = "当问题询问未收录报警、润滑扭矩或维修过程时，答复：现有资料不足，请补充对应型号手册或转人工确认。"
    action = "登记问题、型号、来源文件、版本及缺少的参数；不编造维修结论。"
    safety = "本流程不提供报警复位动作，不授权绕过联锁，不替代现场安全规程。"
    rows = store.collection.get(where={"document_id": document_id}, include=["documents", "metadatas"])
    evidence = []
    for sentence in (condition, action, safety):
        for chunk_id, text, metadata in zip(rows["ids"], rows["documents"], rows["metadatas"], strict=True):
            if (metadata.get("chunk_id") == chunk_id and permitted_chunk(user, metadata, policies)
                    and sentence in text):
                evidence.append(Evidence(
                    evidence_id=f"sop:{chunk_id}:{len(evidence)}", source_type="knowledge",
                    summary=sentence, source_ref=chunk_id, document_id=document_id,
                    policy_version=policy.policy_version, content_version=policy.content_version))
                break
        else:
            return [], []  # Require condition, action and safety together.
    recommendation = Recommendation(
        recommendation_id="simulation-escalation-v2",
        text="现有资料不足，请补充对应型号手册或转人工确认。" + action,
        evidence_ids=[e.evidence_id for e in evidence],
        applicable_conditions=["用户明确询问：" + "、".join(matches),
                               "仅适用于模拟的信息登记与人工升级，不提供设备操作指令"])
    return evidence, [recommendation]
