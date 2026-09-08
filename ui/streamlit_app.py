import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import CHROMA_COLLECTION, CHROMA_PATH, TOP_K
from app.ingestion.indexer import index_txt
from app.retrieval.vector_store import LocalChromaStore
from app.schemas.qa import AskRequest
from app.services.qa_service import answer_question

st.set_page_config(page_title="设备运维知识助手 · Day 1", page_icon="🛠️")
st.title("制造设备运维知识助手 · Day 1 基线")
st.warning("仅使用自制模拟数据；当前结果不是生产维修建议。")

store = LocalChromaStore(CHROMA_PATH, CHROMA_COLLECTION)
demo_path = PROJECT_ROOT / "data/raw_docs/baseline_demo.txt"
index_txt(demo_path, store)

question = st.text_input("问题", value="维护窗口是什么时间？")
run_query = st.button("提问", type="primary")
if run_query or "day1_response" not in st.session_state:
    if not question.strip():
        st.error("请输入问题。")
    else:
        st.session_state["day1_response"] = answer_question(
            store, AskRequest(question=question, top_k=TOP_K)
        )

if response := st.session_state.get("day1_response"):
    st.subheader("回答")
    st.write(response.answer)
    st.caption(f"grounded={response.grounded} · request_id={response.request_id}")
    st.subheader("引用")
    for citation in response.citations:
        with st.expander(f"{citation.source_file} · {citation.chunk_id}"):
            st.write(citation.excerpt)
            st.code(f"distance={citation.distance}")
