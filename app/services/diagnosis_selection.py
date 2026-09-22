"""三源模型选择：本次请求生成随机编号，校验编号归属、建议依赖及冲突集合。

应用根据编号恢复证据，不采用模型自由编写的维修建议；云端异常不回显原始正文。
"""
import json
import os
import secrets
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import PROJECT_ROOT


class DiagnosisSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    evidence_ids: list[str] = Field(max_length=40)
    recommendation_ids: list[str] = Field(max_length=10)
    conflict_evidence_ids: list[str] = Field(max_length=40)


def choose_diagnosis(question, evidence, recommendations, *, transport=None):
    nonce = secrets.token_hex(16)
    evidence_map = {f"{nonce}:E{i}": item for i, item in enumerate(evidence)}
    recommendation_map = {f"{nonce}:R{i}": item for i, item in enumerate(recommendations)}
    reverse = {item.evidence_id: key for key, item in evidence_map.items()}
    payload = {
        "question": question,
        "evidence": [{"id": key, "source_type": item.source_type, "text": item.summary}
                     for key, item in evidence_map.items()],
        "recommendations": [{"id": key, "text": item.text,
                             "conditions": item.applicable_conditions,
                             "evidence_ids": [reverse[e] for e in item.evidence_ids]}
                            for key, item in recommendation_map.items()]}
    raw = (transport or request_selection)(payload)
    selection = DiagnosisSelection.model_validate(raw)
    if (any(key not in evidence_map for key in selection.evidence_ids)
            or any(key not in recommendation_map for key in selection.recommendation_ids)
            or any(key not in selection.evidence_ids for key in selection.conflict_evidence_ids)
            or len(set(selection.conflict_evidence_ids)) == 1):
        raise RuntimeError("Invalid diagnosis selection")
    chosen = [evidence_map[key] for key in dict.fromkeys(selection.evidence_ids)]
    chosen_ids = {item.evidence_id for item in chosen}
    suggestions = [recommendation_map[key] for key in dict.fromkeys(selection.recommendation_ids)]
    if any(not set(item.evidence_ids) <= chosen_ids for item in suggestions):
        raise RuntimeError("Recommendation evidence incomplete")
    conflicts = [evidence_map[key].evidence_id for key in dict.fromkeys(selection.conflict_evidence_ids)]
    # Conflicts are model-flagged, not proven contradictions. Do not issue advice
    # when the same output identifies conflicting evidence; escalate instead.
    return chosen, [] if conflicts else suggestions, conflicts


def request_selection(payload):
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Model configuration unavailable")
    prompt = (PROJECT_ROOT / "app/prompts/diagnosis_prompt.txt").read_text(encoding="utf-8")
    body = {"model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            "messages": [{"role": "system", "content": prompt},
                         {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            "response_format": {"type": "json_object"}, "temperature": 0, "max_tokens": 2500}
    request = Request("https://api.deepseek.com/chat/completions", data=json.dumps(body).encode(),
                      headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=60) as response:
            # Bound response memory and never expose remote errors or raw output.
            data = response.read(131073)
        if len(data) > 131072:
            raise ValueError("Response too large")
        content = json.loads(data)["choices"][0]["message"]["content"]
        return DiagnosisSelection.model_validate_json(content).model_dump()
    except (HTTPError, URLError, TimeoutError, KeyError, IndexError, TypeError, ValueError):
        raise RuntimeError("Diagnosis model unavailable or invalid output") from None
