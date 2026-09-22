"""验收网页测试：默认模拟传输；显式启用时连接本机隔离 HTTPS 验收服务。"""
import os

import pytest
from streamlit.testing.v1 import AppTest

from app.core.config import PROJECT_ROOT
from ui.api_transport import ApiError, call_api

PAGE = PROJECT_ROOT / "ui/acceptance_app.py"


def test_acceptance_page_without_server(monkeypatch):
    monkeypatch.delenv("MAINTENANCE_API_URL", raising=False)
    page = AppTest.from_file(str(PAGE)).run()
    assert not page.exception
    assert page.error and not page.button


def test_acceptance_reader_login_navigation_logout(monkeypatch):
    monkeypatch.setenv("MAINTENANCE_API_URL", "https://example.com")
    def transport(server, method, segments, **kwargs):
        if segments == ["auth", "login"]:
            return {"access_token": "test-only-token"}
        if segments == ["me"]:
            return {"role": "employee", "department_id": "A", "clearance": 1}
        if segments == ["documents"]:
            return [{"resource_id": "SIM_VISIBLE"}]
        if segments == ["auth", "logout"]:
            return {"ok": True}
        raise AssertionError("Unexpected request")
    monkeypatch.setattr("ui.api_transport.call_api", transport)
    page = AppTest.from_file(str(PAGE)).run()
    page.text_input[0].set_value("A1")
    page.text_input[1].set_value("test-password")
    page.button[0].click().run()
    assert not page.exception
    assert "管理员操作" not in page.sidebar.radio[0].options
    page.sidebar.radio[0].set_value("文档与引用").run()
    next(b for b in page.button if b.label == "查看我可读的文档").click().run()
    assert page.json
    next(b for b in page.button if b.label == "退出并换账号").click().run()
    assert not page.exception and not page.json
    assert "acceptance_token" not in page.session_state


@pytest.mark.skipif(os.getenv("RUN_ACCEPTANCE_WEB") != "1", reason="Requires running local acceptance server")
def test_live_acceptance_https_and_page(monkeypatch):
    runtime = PROJECT_ROOT / "data/acceptance-web"
    lines = (runtime / "验收账号（勿上传）.txt").read_text(encoding="utf-8").splitlines()
    credentials = {line.removeprefix("账号："): lines[i + 1].removeprefix("密码：")
                   for i, line in enumerate(lines) if line.startswith("账号：")}
    server = "https://127.0.0.1:18443"
    monkeypatch.setenv("MAINTENANCE_API_URL", server)
    monkeypatch.setenv("MAINTENANCE_CA_FILE", str(runtime / "server.crt"))
    for name in ("A1", "A2", "B1", "admin"):
        token = call_api(server, "POST", ["auth", "login"], payload={
            "username": name, "password": credentials[name]})["access_token"]
        try:
            visible = {d["resource_id"] for d in call_api(server, "GET", ["documents"], token=token)}
            assert "ACCEPT-PUBLIC" in visible
            assert ("ACCEPT-A-SECRET" in visible) == (name == "A2")
            assert ("ACCEPT-B-SECRET" in visible) == (name == "B1")
            if name == "B1":
                with pytest.raises(ApiError) as exc:
                    call_api(server, "GET", ["equipment", "EQ-ROBOT-001"], token=token)
                assert exc.value.status == 404
        finally:
            call_api(server, "POST", ["auth", "logout"], token=token)
    page = AppTest.from_file(str(PAGE), default_timeout=90).run()
    page.text_input[0].set_value("A1")
    page.text_input[1].set_value(credentials["A1"])
    page.button[0].click().run()
    assert not page.exception
    page.sidebar.radio[0].set_value("知识问答").run()
    next(b for b in page.button if b.label == "查询并检查引用").click().run()
    assert not page.exception and not page.error
    assert any("5 kg" in item.value for item in page.markdown)
    page.sidebar.radio[0].set_value("三源诊断").run()
    next(b for b in page.button if b.label == "汇总授权证据").click().run()
    assert not page.exception and not page.error
    assert page.warning
    if os.getenv("RUN_LIVE_DEEPSEEK") == "1":
        page.sidebar.radio[0].set_value("知识问答").run()
        page.selectbox[0].set_value("deepseek").run()
        next(b for b in page.button if b.label == "查询并检查引用").click().run()
        assert not page.exception and not page.error
        assert any("5 kg" in item.value for item in page.markdown)
        page.sidebar.radio[0].set_value("三源诊断").run()
        page.selectbox[0].set_value("deepseek").run()
        next(b for b in page.button if b.label == "汇总授权证据").click().run()
        assert not page.exception and not page.error
        assert page.warning and len(page.expander) >= 3
    next(b for b in page.button if b.label == "退出并换账号").click().run()
