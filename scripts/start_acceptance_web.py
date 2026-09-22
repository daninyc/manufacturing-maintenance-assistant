"""启动本机甲方验收台：隔离数据、随机演示密码、专用 TLS 信任，不改生产数据。

浏览器只连接本机 Streamlit；Streamlit 用验证证书的 HTTPS 调用独立 API。
此启动器不是局域网/生产部署方案，禁止把监听地址改成公网地址直接使用。
"""
import argparse
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

from app.core.config import PROJECT_ROOT

RUNTIME = PROJECT_ROOT / "data/acceptance-web"
API_PORT = 18443
WEB_PORT = 18501


def prepare(runtime=RUNTIME):
    """只在空目录初始化；失败保留证据，不覆盖已有数据。"""
    if (runtime / "ready.json").exists():
        return
    if runtime.exists() and any(runtime.iterdir()):
        raise RuntimeError("验收目录存在但初始化未完成，请交付人员检查；不会自动删除或覆盖。")
    runtime.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        account = subprocess.check_output(["whoami"], text=True).strip()
        subprocess.run(["icacls", str(runtime), "/inheritance:r", "/grant:r",
                        account + ":(OI)(CI)F", "SYSTEM:(OI)(CI)F"], check=True,
                       stdout=subprocess.DEVNULL)
    else:
        runtime.chmod(0o700)
    openssl = shutil.which("openssl")
    if not openssl:
        raise RuntimeError("未找到 OpenSSL，请交付人员配置后启动，不要关闭 TLS 验证。")
    config = Path(openssl).parent.parent / "ssl/openssl.cnf"
    config_args = ["-config", str(config)] if config.is_file() else []
    subprocess.run([openssl, "req", *config_args, "-x509", "-newkey", "rsa:2048", "-nodes",
        "-keyout", "server.key", "-out", "server.crt",
        "-days", "30", "-subj", "/CN=localhost",
        "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1"], check=True,
        cwd=runtime, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    from app.auth.sessions import SessionStore
    from app.db.repositories import MaintenanceRepository
    from app.db.seed import seed_database
    from app.ingestion.publication import publish_document
    from app.retrieval.vector_store import LocalChromaStore
    from app.security.authorization import ResourcePolicy
    from app.security.policies import PolicyStore
    from scripts.label_equipment import label_equipment

    seed_database(runtime / "business.sqlite3")
    sessions = SessionStore(runtime / "access.sqlite3")
    stores = {kind: PolicyStore(sessions, resource_kind=kind)
              for kind in ("document", "equipment", "alarm", "maintenance")}
    for store in stores.values():
        store.initialize()
    credentials = []
    for name, role, department, clearance in (
        ("admin", "admin", "PLATFORM", 2), ("A1", "employee", "A", 1),
        ("A2", "engineer", "A", 2), ("B1", "engineer", "B", 2),
    ):
        password = secrets.token_urlsafe(18)
        sessions.create_user(name, password, role=role, department_id=department, clearance=clearance)
        credentials.append((name, password))
    with (runtime / "验收账号（勿上传）.txt").open("x", encoding="utf-8") as output:
        output.write("仅本机模拟环境。请勿上传Git、截图分享或作为生产密码。\n")
        for name, password in credentials:
            output.write(f"账号：{name}\n密码：{password}\n\n")
    token = sessions.login("admin", credentials[0][1])
    try:
        label_equipment(sessions, token, runtime / "business.sqlite3", "EQ-ROBOT-001",
                        department="A", classification=1)
        for kind in ("equipment", "alarm", "maintenance"):
            for old in stores[kind].list_policies():
                stores[kind].save(old.model_copy(update={"external_processing_allowed": True,
                    "policy_version": old.policy_version + 1}), expected_version=old.policy_version,
                    actor_id=sessions.authenticate(token).user_id, actor_token=token)
        repository = MaintenanceRepository(runtime / "business.sqlite3")
        linked_ids = {r.document_id for r in repository.list_recent_alarms("EQ-ROBOT-001")}
        linked_ids.update(r.document_id for r in repository.list_maintenance_history("EQ-ROBOT-001"))
        vectors = LocalChromaStore(runtime / "chroma", "authorized_v1", semantic=True)
        documents = [
            ("ACCEPT-PUBLIC", "UR5e-public.txt", "模拟 UR5e：额定负载为 5 kg。仅用于软件验收，不作为厂商参数依据。", "A", 0, "organization", True),
            ("ACCEPT-A", "a-check.txt", "模拟设备每日点检需要检查维护记录是否完整，并登记异常后转人工核查。", "A", 1, "department", True),
            ("ACCEPT-A-SECRET", "a-secret.txt", "A部门模拟受限识别码为 SIM_A_RESTRICTED_7301。", "A", 2, "department", True),
            ("ACCEPT-B-SECRET", "b-secret.txt", "B部门模拟受限识别码为 SIM_B_RESTRICTED_8492。", "B", 2, "department", True),
            ("ACCEPT-LOCAL", "local-only.txt", "仅本地模拟校验口令为 SIM_LOCAL_ONLY_5500。", "A", 1, "department", False),
        ]
        for document_id in sorted(linked_ids):
            documents.append((document_id, secrets.token_hex(8) + ".txt",
                "模拟设备每日点检需要检查维护记录是否完整，并登记异常后转人工核查。",
                "A", 1, "department", True))
        sources = runtime / "sources"
        sources.mkdir()
        for document_id, filename, text, department, level, visibility, external in documents:
            source = sources / filename
            if document_id == "SOP-ESCALATION":
                source.write_bytes((PROJECT_ROOT / "data/raw_docs/sops/escalation.txt").read_bytes())
            else:
                source.write_text(text, encoding="utf-8")
            policy = ResourcePolicy(resource_id=document_id, department_id=department,
                classification=level, visibility=visibility, status="draft", policy_version=1,
                content_version="pending", external_processing_allowed=external)
            publish_document(source, policy, vectors, stores["document"], sessions, token,
                expected_version=0, equipment_id=("EQ-ROBOT-002" if document_id == "ACCEPT-PUBLIC"
                    else "EQ-ROBOT-001" if document_id in linked_ids else ""))
        (runtime / "ready.json").write_text(json.dumps({"simulation_only": True,
            "schema": 1, "created_at": time.time()}, indent=2), encoding="utf-8")
    finally:
        sessions.logout(token)


def run_api():
    import uvicorn

    from app.api.server import create_app
    from scripts.serve_api import server_options

    options = server_options("127.0.0.1", API_PORT, certfile=RUNTIME / "server.crt",
                             keyfile=RUNTIME / "server.key")
    options["app"] = create_app(RUNTIME / "access.sqlite3", RUNTIME / "business.sqlite3", RUNTIME / "chroma")
    uvicorn.run(**options)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if args.api:
        run_api()
        return
    for port in (API_PORT, WEB_PORT):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                raise SystemExit(f"端口 {port} 已使用。请检查是否已经启动；不会终止未知进程。")
    print("准备独立验收环境，首次需要加载本地语义模型……", flush=True)
    prepare()
    print("验收账号文件：" + str(RUNTIME / "验收账号（勿上传）.txt"), flush=True)
    if args.prepare_only:
        return
    environment = os.environ.copy()
    environment.update(MAINTENANCE_API_URL=f"https://127.0.0.1:{API_PORT}",
                       MAINTENANCE_CA_FILE=str(RUNTIME / "server.crt"),
                       PYTHONIOENCODING="utf-8")
    processes = []
    logs = []
    try:
        for name, command in (
            ("api", [sys.executable, "-m", "scripts.start_acceptance_web", "--api"]),
            ("web", [sys.executable, "-m", "streamlit", "run", "ui/acceptance_app.py",
                "--server.address=127.0.0.1", f"--server.port={WEB_PORT}", "--server.headless=true",
                "--browser.gatherUsageStats=false"]),
        ):
            log = (RUNTIME / (name + ".log")).open("a", encoding="utf-8")
            logs.append(log)
            processes.append(subprocess.Popen(command, cwd=PROJECT_ROOT, env=environment,
                stdout=log, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0))
        # 仅检查本次启动的子进程；端口就绪不代表业务验收通过。
        for _ in range(60):
            if any(p.poll() is not None for p in processes):
                raise RuntimeError("服务启动失败，请交付人员检查 data/acceptance-web 中的日志。")
            ready = True
            for port in (API_PORT, WEB_PORT):
                with socket.socket() as probe:
                    ready = ready and probe.connect_ex(("127.0.0.1", port)) == 0
            if ready:
                break
            time.sleep(1)
        else:
            raise RuntimeError("网页启动超时，请检查日志。")
        print(f"浏览器打开：http://127.0.0.1:{WEB_PORT}", flush=True)
        print("请保持本窗口开启。完成后按 Ctrl+C 停止本次启动的服务。", flush=True)
        if not args.no_browser:
            webbrowser.open(f"http://127.0.0.1:{WEB_PORT}")
        while all(p.poll() is None for p in processes):
            time.sleep(1)
    except KeyboardInterrupt:
        print("正在停止本次验收服务……", flush=True)
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for log in logs:
            log.close()


if __name__ == "__main__":
    main()
