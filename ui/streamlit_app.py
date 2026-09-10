import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import CHROMA_PATH, DAY2_COLLECTION, MAX_DISTANCE
from app.retrieval.vector_store import LocalChromaStore
from app.schemas.qa import AskRequest
from app.services.qa_service import answer_question

st.set_page_config(page_title="设备运维知识助手 · Day 2", page_icon="🛠️")
st.title("制造设备运维知识助手 · Day 2")
st.caption("官方规格事实＋模拟资产；回答附原文摘录。教学内容不代替现场规程。")

store = LocalChromaStore(CHROMA_PATH, DAY2_COLLECTION, semantic=True)
if store.collection.count() == 0:
    st.info("请先在项目根目录执行 python -m scripts.ingest 完成资料入库。")
    st.stop()
mode = st.selectbox("回答模式", ["local", "deepseek"],
                    format_func=lambda value: "本地规格摘录（有限规则）" if value == "local" else "DeepSeek 证据选择")
st.caption("本地模式支持含型号的负载、半径、温度问题；DeepSeek 模式需在 .env 配置密钥。")
top_k = st.slider("候选块数量", 1, 10, 6)

question = st.text_input("问题", value="比较 UR3e 与 UR5e 的负载和工作半径。")
run_query = st.button("提问", type="primary")
if run_query:
    if not question.strip():
        st.error("请输入问题。")
    else:
        st.session_state.pop("day2_response", None)
        try:
            with st.spinner("检索并核验证据……"):
                st.session_state["day2_response"] = answer_question(
                    store, AskRequest(question=question, top_k=top_k),
                    mode=mode, max_distance=MAX_DISTANCE)
        except (RuntimeError, ValueError) as exc:
            st.error(str(exc))

if response := st.session_state.get("day2_response"):
    st.subheader("回答")
    st.write(response.answer)
    st.caption(f"grounded={response.grounded} · request_id={response.request_id}")
    st.subheader("引用")
    for citation in response.citations:
        with st.expander(f"{citation.source_file} · 第 {citation.page} 页 · {citation.chunk_id}"):
            st.write(citation.excerpt)
            st.code(f"distance={citation.distance}")
            if citation.source_url:
                st.link_button("查看官方来源", citation.source_url)
