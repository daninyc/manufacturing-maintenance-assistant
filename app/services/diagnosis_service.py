"""诊断编排：汇总授权知识、报警和维修证据，选择受条件约束的参考建议。

模型调用后复核权限快照；历史维修不是当前许可，grounded=False 表示未确认根因。
"""
from uuid import uuid4

from app.auth.sessions import AuthenticationError
from app.schemas.diagnosis import DiagnoseRequest, DiagnoseResponse, Evidence
from app.schemas.qa import AskRequest
from app.security.authorization import can_process_externally, permitted_chunk
from app.services.diagnosis_selection import choose_diagnosis
from app.services.protected_data import ResourceUnavailable
from app.services.protected_qa import authorized_answer
from app.services.sop_recommendations import escalation_recommendation


def diagnose(business, store, token: str, request: DiagnoseRequest, *, mode="local", selector=None,
             diagnosis_transport=None):
    sessions = business.sessions
    initial = sessions.authenticate(token)
    # Snapshot all policy versions across the multi-step operation, not only
    # each individual subquery. A changed policy invalidates the whole result.
    before = {kind: policy_store.list_policies() for kind, policy_store in business.stores.items()}
    business.query(token, "equipment", request.equipment_id)
    period = {"start_time": request.start_time, "end_time": request.end_time}
    alarms = business.query(token, "alarms", request.equipment_id, limit=10, **period)
    history = business.query(token, "maintenance", request.equipment_id, limit=10, **period)
    # Document evidence selection has its own authorization/external-send gate.
    answer = authorized_answer(store, business.stores["document"], sessions, token,
                               AskRequest(question=request.symptom, equipment_id=request.equipment_id),
                               mode=mode, selector=selector)
    policies = {kind: {p.resource_id: p for p in entries} for kind, entries in before.items()}
    evidence = []
    for kind, rows in (("alarm", alarms), ("maintenance", history)):
        for row in rows:
            resource_id = row.alarm_id if kind == "alarm" else row.record_id
            policy = policies[kind].get(resource_id)
            if policy is None:
                raise ResourceUnavailable()
            summary = (f"{row.occurred_at.isoformat()} | {row.code} | {row.severity} | {row.message}"
                       if kind == "alarm" else
                       f"历史记录（不是当前操作许可）：{row.maintained_at.isoformat()} | "
                       f"{row.symptom} | {row.action} | {row.result}")
            evidence.append(Evidence(evidence_id=f"{kind}:{resource_id}", source_type=kind,
                                     summary=summary, source_ref=resource_id,
                                     document_id=row.document_id, policy_version=policy.policy_version,
                                     content_version=policy.content_version))
    for citation in answer.citations:
        found = store.collection.get(ids=[citation.chunk_id], include=["metadatas", "documents"])
        if not found["ids"]:
            raise ResourceUnavailable()
        metadata = found["metadatas"][0]
        document_id = metadata.get("document_id")
        policy = policies["document"].get(document_id)
        if (not permitted_chunk(initial, metadata, policies["document"])
                or metadata.get("chunk_id") != citation.chunk_id
                or document_id != citation.document_id
                or metadata.get("policy_version") != citation.policy_version
                or metadata.get("content_version") != citation.content_version
                or citation.excerpt not in found["documents"][0]):
            raise ResourceUnavailable()
        evidence.append(Evidence(evidence_id="knowledge:" + citation.chunk_id, source_type="knowledge",
                                 summary=citation.excerpt, source_ref=citation.chunk_id,
                                 document_id=document_id, policy_version=policy.policy_version,
                                 content_version=policy.content_version))
    sop_evidence, recommendations = escalation_recommendation(
        store, initial, policies["document"], request.symptom)
    evidence.extend(sop_evidence)
    def revalidate():
        if sessions.authenticate(token) != initial:
            raise AuthenticationError()
        if any(policy_store.list_policies() != before[kind]
               for kind, policy_store in business.stores.items()):
            raise ResourceUnavailable()

    revalidate()
    conflicts = []
    if mode == "deepseek" and evidence:
        # All business context and referenced documents must independently allow
        # external processing. Read access alone is never sufficient.
        required = [policies["equipment"].get(request.equipment_id)]
        for item in evidence:
            required.append(policies["document"].get(item.document_id))
            if item.source_type != "knowledge":
                required.append(policies[item.source_type].get(item.source_ref))
        if not all(can_process_externally(initial, policy) for policy in required):
            raise ResourceUnavailable()
        try:
            evidence, recommendations, conflicts = choose_diagnosis(
                request.symptom, evidence, recommendations, transport=diagnosis_transport)
        except (ValueError, KeyError):
            raise RuntimeError("Invalid diagnosis selection") from None
        revalidate()
    critical = any(row.severity == "critical" and not row.resolved for row in alarms)
    return DiagnoseResponse(
        phenomenon=request.symptom, evidence=evidence,
        suggestions=[r.text for r in recommendations], recommendation_details=recommendations,
        conflict_evidence_ids=conflicts,
        risk_notice="仅汇总当前可读证据，未确认故障根因。历史动作不构成当前操作许可；"
                    "建议仅限通过条件校验的模拟 SOP 信息登记与人工升级，不提供设备操作许可。",
        grounded=False, request_id=str(uuid4()),
        status="human_review" if critical or conflicts else "evidence_only" if evidence else "insufficient_evidence")
