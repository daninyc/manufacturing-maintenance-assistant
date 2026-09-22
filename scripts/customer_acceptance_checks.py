"""客户一键回归：固定测试范围、保存退出码，不把跳过或未测专项称为通过。"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

from app.core.config import PROJECT_ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=["offline", "model", "web", "security"], default="offline")
    args = parser.parse_args()
    environment = os.environ.copy()
    environment.pop("RUN_LIVE_DEEPSEEK", None)
    environment.pop("RUN_ACCEPTANCE_WEB", None)
    environment["PYTHONIOENCODING"] = "utf-8"
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=short"]
    if args.suite == "model":
        environment["RUN_LIVE_DEEPSEEK"] = "1"
        command += ["tests/integration/test_protected_qa.py", "tests/integration/test_diagnosis.py",
                    "-k", "live_deepseek or live_three_source"]
    elif args.suite == "web":
        environment["RUN_ACCEPTANCE_WEB"] = "1"
        environment["RUN_LIVE_DEEPSEEK"] = "1"
        command += ["tests/integration/test_acceptance_web.py"]
    elif args.suite == "security":
        command += ["tests/unit/test_authorization.py", "tests/unit/test_sessions.py",
                    "tests/integration/test_protected_qa.py", "tests/integration/test_protected_data.py",
                    "tests/integration/test_api_auth.py", "tests/integration/test_document_upload.py",
                    "tests/integration/test_diagnosis.py"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory = PROJECT_ROOT / "data/customer-acceptance-evidence" / (stamp + "-" + args.suite)
    directory.mkdir(parents=True, exist_ok=False)
    print("正在执行测试，请保持窗口开启。model/web 会真实调用 DeepSeek。", flush=True)
    with (directory / "test-output.txt").open("w", encoding="utf-8") as output:
        result = subprocess.run(command, cwd=PROJECT_ROOT, env=environment,
                                stdout=output, stderr=subprocess.STDOUT, check=False)
    metadata = {"suite": args.suite, "utc": stamp, "exit_code": result.returncode,
                "scope": "仅指定自动测试；不证明客户部署、恢复、压测、完整攻击语料已通过"}
    (directory / "result.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print("测试进程成功结束。仍须查看 skipped/warnings。" if result.returncode == 0
          else "测试没有全部通过，请保留记录并联系交付人员。")
    print("结果目录：" + str(directory))
    print("请打开 test-output.txt，看最后几行；不要未经检查就分享完整日志。")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
