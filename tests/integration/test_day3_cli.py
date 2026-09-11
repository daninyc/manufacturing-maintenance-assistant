import json
import os
import shutil
import subprocess
import sys

import pytest

from app.core.config import PROJECT_ROOT


@pytest.mark.parametrize("limit", ["abc", "--1", "0", "51"])
def test_cli_invalid_limit_returns_structured_error(tmp_path, limit):
    result = subprocess.run([sys.executable, "-m", "scripts.day3_query", "alarms",
                             "--equipment-id", "EQ-ROBOT-001", f"--limit={limit}",
                             "--db", str(tmp_path / "missing.sqlite3")],
                            cwd=PROJECT_ROOT, capture_output=True, encoding="utf-8", check=False,
                            env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=15)
    body = json.loads(result.stdout)
    assert result.returncode == 1 and body["code"] == "INPUT_ERROR"
    assert body["request_id"] and "Traceback" not in result.stderr


def test_smoke_reports_are_distinct_and_pass(tmp_path, monkeypatch):
    from app.db.seed import seed_database
    from scripts import run_day3_smoke
    (tmp_path / "data/seed").mkdir(parents=True)
    shutil.copyfile(PROJECT_ROOT / "data/seed/empty_history.json", tmp_path / "data/seed/empty_history.json")
    monkeypatch.setattr(run_day3_smoke, "PROJECT_ROOT", tmp_path)
    path = tmp_path / "smoke.sqlite3"
    seed_database(path)
    first, second = run_day3_smoke.run(path), run_day3_smoke.run(path)
    assert first["passed"] == first["total"] == 22
    assert second["passed"] == second["total"] == 22
    assert first["run_id"] != second["run_id"]
