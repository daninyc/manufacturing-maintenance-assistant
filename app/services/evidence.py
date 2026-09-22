"""选择证据，不预存测试题答案；在线模式也只能返回可核验摘录。"""
import json
import os
import re
import secrets
from itertools import pairwise
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import PROJECT_ROOT
from app.retrieval.retriever import RetrievedChunk


class EvidenceQuote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chunk_id: str
    excerpt: str = Field(min_length=1, max_length=240)


class EvidenceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    supported: bool
    quotes: list[EvidenceQuote] = Field(default_factory=list, max_length=6)


class SelectedEvidenceIds(BaseModel):
    """在线响应只允许编号；原文和来源由应用持有。"""
    model_config = ConfigDict(extra="forbid", strict=True)
    supported: bool
    evidence_ids: list[str] = Field(default_factory=list, max_length=6)


class EvidenceError(ValueError):
    """在业务拒答中保留明确原因码，消息不包含密钥。"""
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def build_candidates(chunks: list[RetrievedChunk]) -> dict[str, EvidenceQuote]:
    """生成不超过 240 字符的连续原文片段，编号仅对当前请求有效。

    中文按句末标点；英文句点后只有空白接大写字母才视为句界，
    不在小数点处分句。超长段优先在换行处分段，否则重叠取窗口。
    这是保守的文本切分，不保证理解表格和跨句条件；模型仍需检查完整性。
    """
    candidates = {}
    request_nonce = secrets.token_hex(16)
    for chunk in chunks:
        boundaries = [0] + [m.end() for m in re.finditer(
            r"[。！？!?]|\.(?=\s+[A-Z\u4e00-\u9fff]|$)", chunk.text)] + [len(chunk.text)]
        for start, end in pairwise(boundaries):
            while start < end:
                stop = min(start + 240, end)
                if stop < end:
                    newline = chunk.text.rfind("\n", start + 120, stop)
                    if newline != -1:
                        stop = newline
                excerpt = chunk.text[start:stop].strip()
                if excerpt:
                    candidate_id = f"{request_nonce}:E{len(candidates) + 1:03d}"
                    candidates[candidate_id] = EvidenceQuote(
                        chunk_id=str(chunk.metadata["chunk_id"]), excerpt=excerpt)
                if stop == end:
                    break
                start = max(start + 1, stop - 40)
    return candidates


def resolve_selection(selected: SelectedEvidenceIds,
                      candidates: dict[str, EvidenceQuote]) -> EvidenceSelection:
    """先验证全部编号，再去重；绝不悄悄丢掉非法编号后宣称成功。"""
    if not selected.supported:
        return EvidenceSelection(supported=False)
    if not selected.evidence_ids:
        raise EvidenceError("EMPTY_SELECTION")
    if any(evidence_id not in candidates for evidence_id in selected.evidence_ids):
        raise EvidenceError("UNKNOWN_EVIDENCE_ID")
    return EvidenceSelection(supported=True, quotes=[
        candidates[evidence_id] for evidence_id in dict.fromkeys(selected.evidence_ids)])


def select_with_deepseek(question: str, chunks: list[RetrievedChunk],
                         *, trace: dict | None = None) -> EvidenceSelection:
    """密钥仅从环境读取；不输出请求头、密钥或远端错误响应正文。"""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY，请在项目 .env 中设置")
    prompt = (PROJECT_ROOT / "app/prompts/qa_prompt.txt").read_text(encoding="utf-8")
    candidates = build_candidates(chunks)
    by_id = {str(chunk.metadata["chunk_id"]): chunk for chunk in chunks}
    if trace is not None:
        trace["candidates"] = {key: value.model_dump() for key, value in candidates.items()}
    body = {"model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            "messages": [{"role": "system", "content": prompt},
                         {"role": "user", "content": json.dumps({
                             "question": question,
                             "context": [{"evidence_id": key, "text": quote.excerpt,
                                          "source_file": by_id[quote.chunk_id].metadata["source_file"],
                                          "chunk_id": quote.chunk_id}
                                         for key, quote in candidates.items()]}, ensure_ascii=False)}],
            "response_format": {"type": "json_object"}, "temperature": 0, "max_tokens": 1800}
    request = Request("https://api.deepseek.com/chat/completions",
                      data=json.dumps(body).encode("utf-8"),
                      headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=60) as response:
            raw = response.read(131073)
        if len(raw) > 131072:
            raise ValueError("Response too large")
        payload = json.loads(raw)
        selected = SelectedEvidenceIds.model_validate_json(payload["choices"][0]["message"]["content"])
        if trace is not None:
            trace["model_selection"] = selected.model_dump()
    except HTTPError as exc:
        if trace is not None:
            trace["http_status"] = exc.code
        raise RuntimeError(f"DeepSeek HTTP {exc.code}，请检查模型配置、密钥或额度") from None
    except (URLError, TimeoutError, KeyError, IndexError, TypeError, ValueError):
        raise RuntimeError("DeepSeek 请求失败或返回不符合证据结构") from None
    return resolve_selection(selected, candidates)


def select_locally(question: str, chunks: list[RetrievedChunk]) -> EvidenceSelection:
    """离线规格摘录模式，只处理负载/半径/温度，不冒充通用语言模型。

    规则决定要找的字段，实际参数必须从检索出的句子读取。
    不支持的维修问题保守拒答；这不是安全分类器或完整意图理解器。
    """
    fields = []
    for pattern, field in [(r"负载|载荷|承重|payload", "负载"),
                           (r"半径|臂展|范围|reach", "半径"),
                           (r"温度|temperature", "温度")]:
        if re.search(pattern, question, re.IGNORECASE):
            fields.append(field)
    if not fields or re.search(r"扭矩|润滑|复位|拆卸|联锁|维修|价格|售价|多少钱|所有工况|任何工况", question):
        return EvidenceSelection(supported=False)
    models = re.findall(r"UR\d+e|IRB\s*\d+", question, re.IGNORECASE)
    models = list(dict.fromkeys(model.upper().replace(" ", "") for model in models))
    if not models:
        return EvidenceSelection(supported=False)
    quotes = []
    for model in models:
        found = set()
        for chunk in chunks:
            # 模型标识从来源文件识别，避免把另一台设备的数字拼入答案。
            source = str(chunk.metadata["source_file"]).upper().replace("_", "").replace(" ", "")
            if model not in source:
                continue
            for line in chunk.text.splitlines():
                matched = set()
                if "负载" in fields and "负载" in line and re.search(r"\d+\s*kg", line):
                    matched.add("负载")
                if "半径" in fields and re.search(r"半径|工作范围", line) and re.search(r"\d+\s*mm", line):
                    matched.add("半径")
                if "温度" in fields and re.search(r"环境范围|温度", line) and "°C" in line:
                    matched.add("温度")
                if matched - found and len(line) <= 240 and not re.search(r"禁忌|不得|误标", line):
                    quotes.append(EvidenceQuote(chunk_id=str(chunk.metadata["chunk_id"]), excerpt=line))
                    found |= matched
        if found != set(fields):
            return EvidenceSelection(supported=False)
    return EvidenceSelection(supported=bool(quotes), quotes=quotes[:6])
