"""面向甲方的验收工作台：仅调用 HTTPS API，不读取模型、业务库或演示密码文件。"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ui.api_transport import ApiError, call_api, validate_server

st.set_page_config(page_title="Agent 客户验收工作台", layout="wide")
st.title("Agent 客户验收工作台")
st.caption("仅模拟资料 · 每次操作真实调用后端 · 网页通过不等于完整安全验收通过")

try:
    server = validate_server(os.getenv("MAINTENANCE_API_URL", ""))
except (ApiError, ValueError):
    st.error("验收服务尚未配置。请双击项目目录中的 启动网页版验收.cmd。")
    st.stop()
if st.session_state.get("acceptance_server") != server:
    st.session_state.clear()
    st.session_state["acceptance_server"] = server


def api(method, parts, **kwargs):
    try:
        return call_api(server, method, parts, token=st.session_state.get("acceptance_token"), **kwargs)
    except ApiError as exc:
        messages = {401: "登录失效或凭证错误，请重新登录。", 403: "当前角色没有管理权限。",
                    404: "资源不存在或当前账号无权访问（不区分这两种原因）。",
                    409: "版本已变化或不处于草稿状态，请刷新后重试。",
                    413: "文件超过允许大小。", 422: "输入不符合要求，请检查必填项和格式。",
                    429: "操作过于频繁，请稍后再试。", 503: "后端依赖不可用，请记录时间并联系交付人员。"}
        st.error(f"请求未完成，HTTP {exc.status or '未知'}：" + messages.get(exc.status, "检查服务窗口和网络连接。"))
        if exc.status == 401:
            st.session_state.clear()
        st.stop()


if not st.session_state.get("acceptance_token"):
    st.info("第一步：打开启动窗口提示的验收账号文件，复制账号与对应密码。不要发送密码截图。")
    with st.form("acceptance_login", clear_on_submit=True):
        name = st.text_input("账号", placeholder="例如 A1")
        password = st.text_input("密码", type="password")
        login = st.form_submit_button("登录验收", type="primary")
    if login:
        result = api("POST", ["auth", "login"], payload={"username": name, "password": password})
        st.session_state["acceptance_token"] = result["access_token"]
        st.rerun()
    st.warning("功能已具备测试入口，但尚未最终签收。不要上传真实企业文件。")
    st.stop()

person = api("GET", ["me"])
st.sidebar.header("当前身份")
st.sidebar.write(f"角色：{person['role']}\n\n部门：{person['department_id']}\n\n最高密级：{person['clearance']}")
st.sidebar.caption("公开=0，内部=1，受限=2。身份由服务端决定。")
if st.sidebar.button("退出并换账号"):
    old_token = st.session_state.get("acceptance_token")
    st.session_state.clear()
    try:
        call_api(server, "POST", ["auth", "logout"], token=old_token)
    except ApiError:
        st.warning("网页已清理，但服务器撤销未确认。请联系交付人员。")
        st.stop()
    st.rerun()

pages = ["验收指引", "知识问答", "设备与记录", "三源诊断", "文档与引用", "填写验收记录"]
if person["role"] == "admin":
    pages.append("管理员操作")
page = st.sidebar.radio("选择验收项目", pages)
st.sidebar.info("页面不保存业务回答；切换项目或刷新后请重新查询，以免复用过期结果。")

if page == "验收指引":
    st.header("建议按这个顺序操作")
    st.markdown("1. 用 A1 登录，查看可见文档及设备。\n2. 测试本地规格问答，再测试 DeepSeek。\n3. 查看报警、维修，运行三源诊断。\n4. 退出，分别用 A2、B1、admin 对比权限。\n5. 管理员下线模拟文档后，原账号重新查询。\n6. 在‘填写验收记录’导出你的实际观察。")
    st.table([
        {"账号": "A1", "部门": "A", "密级": "内部", "预期": "公共、A内部；不见A受限/B受限"},
        {"账号": "A2", "部门": "A", "密级": "受限", "预期": "比A1多A受限；仍不见B受限"},
        {"账号": "B1", "部门": "B", "密级": "受限", "预期": "公共、B受限；不见A文档/设备"},
        {"账号": "admin", "部门": "PLATFORM", "密级": "受限", "预期": "可管理；正文只读公共资料"},
    ])
    st.warning("‘当前可用资料不足’不一定是故障，也可能是没有权限或问题没有证据。请按指定样例判定。")
    st.write("整体状态：核心链路可测；恢复、并发、日志安全及客户部署仍需线下专项。")

elif page == "知识问答":
    st.header("知识问答与证据")
    st.info("合格：有依据的回答带原文引用；无权限资料不出现。DeepSeek 使用真实云端模型，可能产生费用。")
    mode = st.selectbox("模式", ["local", "deepseek"], format_func=lambda x: "本地规格摘录" if x == "local" else "DeepSeek 真实模型")
    question = st.text_area("你的问题", "UR5e 的负载是多少？")
    st.caption("模拟 UR5e 文档用于验证流程，不作为厂商参数依据。A内部样例问题：模拟设备每日点检需要检查什么？")
    if st.button("查询并检查引用", type="primary"):
        with st.spinner("正在调用后端并校验证据……"):
            result = api("POST", ["ask"], payload={"question": question, "top_k": 3, "mode": mode})
            for citation in result["citations"]:
                current = api("GET", ["documents", citation["document_id"], "chunks", citation["chunk_id"]])
                if (current["policy_version"] != citation["policy_version"]
                        or current["content_version"] != citation["content_version"]
                        or citation["excerpt"] not in current["excerpt"]):
                    st.error("引用已变化，本次回答不展示。请重新查询。")
                    st.stop()
        st.subheader("本次回答")
        st.write(result["answer"])
        st.caption(f"有证据支持：{result['grounded']}；请求编号：{result['request_id']}")
        for citation in result["citations"]:
            with st.expander(f"原文：{citation['source_file']}", expanded=True):
                st.write(citation["excerpt"])
                st.code(f"文档ID：{citation['document_id']}\n块ID：{citation['chunk_id']}")

elif page == "设备与记录":
    st.header("设备、报警、维修")
    st.info("用 A1/A2 可查询 EQ-ROBOT-001；用 B1 查询同一设备应拒绝，不应显示设备详情。")
    if st.button("查看我的设备列表"):
        st.json(api("GET", ["equipment"]))
    equipment = st.text_input("设备编号", "EQ-ROBOT-001")
    operation = st.selectbox("要查看的内容", ["设备详情", "报警记录", "维修记录"])
    if st.button("读取记录"):
        parts = ["equipment", equipment]
        if operation != "设备详情":
            parts.append("alarms" if operation == "报警记录" else "maintenance")
        st.json(api("GET", parts))

elif page == "三源诊断":
    st.header("辅助诊断，不是维修指令")
    st.info("合格：展示现有证据、来源和风险；不能凭历史维修记录声称当前已获操作许可。grounded=false 在诊断中表示未确认根因，并非程序坏了。")
    equipment = st.text_input("设备编号", "EQ-ROBOT-001")
    symptom = st.text_area("现象或问题", "模拟设备每日点检需要检查什么？请结合报警和维修历史登记并转人工核查。")
    mode = st.selectbox("诊断模式", ["local", "deepseek"])
    if st.button("汇总授权证据", type="primary"):
        with st.spinner("正在查询知识、报警和维修历史……"):
            result = api("POST", ["diagnose"], payload={"equipment_id": equipment, "symptom": symptom, "mode": mode})
        st.warning(result["risk_notice"])
        st.write("处理状态：", result["status"])
        st.caption("请求编号：" + result["request_id"])
        for evidence in result["evidence"]:
            with st.expander(evidence["source_type"] + " · " + evidence["source_ref"], expanded=True):
                st.write(evidence["summary"])
        st.subheader("允许的建议")
        st.write(result["suggestions"] or "没有满足条件的操作建议，请人工核查。")

elif page == "文档与引用":
    st.header("验证文档可见范围")
    if st.button("查看我可读的文档"):
        st.json(api("GET", ["documents"]))
    st.caption("在这里填入其他账号得到的文档ID/块ID，可测试猜引用是否越权；被拒绝才是正确结果。")
    doc_id = st.text_input("文档 ID")
    chunk_id = st.text_input("块 ID")
    if st.button("重新鉴权读取片段"):
        if not doc_id or not chunk_id:
            st.error("请填写两个 ID。")
        else:
            st.json(api("GET", ["documents", doc_id, "chunks", chunk_id]))

elif page == "管理员操作":
    st.header("仅操作隔离验收环境")
    st.warning("变更会真实写入验收数据库。保存草稿/下线会暂停文档读取；不要操作真实企业资料。")
    if st.button("查看文档策略及当前版本"):
        st.json(api("GET", ["admin", "documents"], query={"limit": 50}))
    with st.form("policy"):
        doc_id = st.text_input("目标文档 ID", "ACCEPT-A")
        expected = st.number_input("当前策略版本（新文档填0）", min_value=0, step=1, value=2)
        department = st.text_input("归属部门", "A")
        classification = st.selectbox("文档密级", [0, 1, 2], index=1)
        visibility = st.selectbox("可见范围", ["department", "organization"])
        content_version = st.text_input("当前内容版本（从策略列表复制；新文档填pending）", "pending")
        external = st.checkbox("确认仅模拟资料且允许发送 DeepSeek", value=False)
        status = st.selectbox("目标状态", ["draft", "disabled"])
        confirmed = st.checkbox("我确认修改的是验收文档")
        save = st.form_submit_button("提交标签变更")
    if save:
        if not confirmed:
            st.error("请先确认操作范围。")
        else:
            st.json(api("PATCH", ["admin", "documents", doc_id, "policy"], payload={
                "expected_version": expected, "policy": {"resource_id": doc_id,
                "department_id": department, "classification": classification,
                "visibility": visibility, "status": status, "policy_version": expected + 1,
                "content_version": content_version, "external_processing_allowed": external}}))
    st.subheader("上传并发布草稿")
    upload_id = st.text_input("已建草稿的文档 ID", "ACCEPT-NEW")
    upload_version = st.number_input("草稿策略版本", min_value=1, step=1, value=1)
    upload = st.file_uploader("选择模拟 PDF/TXT（不超过10MiB）", type=["txt", "pdf"])
    if st.button("上传并发布"):
        if upload is None:
            st.error("请先选择文件。")
        else:
            fmt = Path(upload.name).suffix.lower()[1:]
            st.json(api("POST", ["admin", "documents", upload_id, "content"],
                query={"expected_version": upload_version, "format": fmt}, raw=upload.getvalue(),
                content_type="text/plain" if fmt == "txt" else "application/pdf"))

elif page == "填写验收记录":
    st.header("记录观察，不自动宣称通过")
    st.caption("仅填写编号和现象，不填写密码、token 或真实内部正文。下载内容是人工记录，不是自动化验收报告。")
    case = st.text_input("用例编号", "WEB-01")
    verdict = st.selectbox("你的判定", ["未执行", "通过", "失败", "需要解释"])
    note = st.text_area("实际看到的现象")
    report = {"time": datetime.now(timezone.utc).isoformat(), "case": case,
              "verdict": verdict, "note": note, "role": person["role"],
              "department": person["department_id"], "source": "客户人工记录，非自动结论"}
    st.download_button("下载本条验收记录", json.dumps(report, ensure_ascii=False, indent=2),
                       file_name="验收记录.json", mime="application/json")
