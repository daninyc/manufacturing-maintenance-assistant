import os
import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ui.api_transport import ApiError, call_api, validate_server

st.set_page_config(page_title="设备运维知识助手 · API 调试")
st.title("设备运维知识助手 · API 调试")
st.caption("模拟，不替代现场规程。此页面不直接访问知识库或模型。")

try:
    server = validate_server(os.getenv("MAINTENANCE_API_URL", ""))
except (ApiError, ValueError):
    st.info("请设置 MAINTENANCE_API_URL 为可信 HTTPS 后端根地址。")
    st.stop()
if st.session_state.get("api_server") != server:
    st.session_state.clear()
    st.session_state["api_server"] = server
token = st.session_state.get("api_token")
if not token:
    with st.form("login", clear_on_submit=True):
        username = st.text_input("账号")
        password = st.text_input("密码", type="password")
        submit = st.form_submit_button("登录")
    if submit:
        try:
            login = call_api(server, "POST", ["auth", "login"], payload={
                "username": username, "password": password})
            st.session_state["api_token"] = login["access_token"]
            st.rerun()
        except (ApiError, KeyError, TypeError):
            st.error("登录失败，请检查账号或后端连接。")
    st.stop()
try:
    call_api(server, "GET", ["me"], token=token)
except ApiError:
    st.session_state.clear()
    st.warning("会话无法验证，请重新登录。")
    st.stop()
if st.button("退出"):
    st.session_state.clear()
    try:
        call_api(server, "POST", ["auth", "logout"], token=token)
    except ApiError:
        st.warning("本机已清理，服务器撤销未确认。")
        st.stop()
    st.rerun()
mode = st.selectbox("回答模式", ["local", "deepseek"],
                    format_func=lambda value: "本地规格摘录（有限规则）" if value == "local" else "DeepSeek 证据选择")
st.caption("本地模式支持有限规格摘录。模型密钥仅配置在 API 后端。")
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
                st.session_state["day2_response"] = call_api(server, "POST", ["ask"], token=token,
                    payload={"question": question, "top_k": top_k, "mode": mode})
        except ApiError:
            st.error("查询未完成，请检查权限、问题或后端状态。")

if response := st.session_state.get("day2_response"):
    try:
        for citation in response["citations"]:
            current = call_api(server, "GET", ["documents", citation["document_id"],
                               "chunks", citation["chunk_id"]], token=token)
            if (current["policy_version"] != citation["policy_version"]
                    or current["content_version"] != citation["content_version"]
                    or citation["excerpt"] not in current["excerpt"]):
                raise ApiError()
    except (ApiError, KeyError, TypeError):
        st.session_state.pop("day2_response", None)
        st.warning("引用权限或版本无法验证，已清空回答。")
        st.stop()
    st.subheader("回答")
    st.write(response["answer"])
    st.caption(f"grounded={response['grounded']} · request_id={response['request_id']}")
    st.subheader("引用")
    for citation in response["citations"]:
        with st.expander(citation["source_file"]):
            st.write(citation["excerpt"])
