"""完整内核调用链：真实状态、Git 和子进程，仅模型端用固定夹具替代。"""
import importlib
import json
import os
from pathlib import Path
import sys
import threading
import time

import pytest

from test_git_snapshot import git, repo


@pytest.fixture
def runtime(repo, tmp_path):
    api = importlib.import_module("codereview_core.runtime")
    from codereview_core import engine
    config = tmp_path / "engine-config.json"
    config.write_text(json.dumps({"llm": {"url": "https://test.invalid/v1", "auth_token": "fake-only",
        "model": "fixture-model", "use_anthropic": False}}))
    fixture = Path(__file__).parent / "fixtures/ocr_process.py"
    environment = os.environ.copy()
    environment["FIXTURE_MARKER"] = str(tmp_path / "calls")
    environment["FIXTURE_DELAY"] = ".2"
    ocr = engine.OCR([sys.executable, str(fixture)], config_path=config, environment=environment)
    (repo / "a.py").write_text("candidate\n")
    # 新语义下 commit 走 remind（无 task），老 codereview 流程测试改为 push。
    # push 路径需要 HEAD 存在，但不允许抢 stage（老测试依赖后续 add + commit），
    # 所以 --allow-empty 创建 HEAD 占位，不 add a.py。
    git(repo, "commit", "--allow-empty", "-qm", "base")
    return api.Runtime(tmp_path / "state", "codex", "session", repo, ocr=ocr,
                       execution_mode="ocr-managed")


def test_end_to_end_consent_review_proceed_then_new_task(runtime, repo):
    pending = runtime.prepare("git push origin main")
    assert pending["action"] == "ask_user"
    with pytest.raises(ValueError, match="not_authorized"):
        runtime.review(pending["task_id"])
    runtime.decide(pending["task_id"], "once", "user:1", pending["scope"])
    report = runtime.review(pending["task_id"])
    assert report["execution_status"] == "success"
    assert report["engine_version"] == "1.12.9"
    assert report["coverage_status"] == "limited"
    assert runtime.prepare("git push origin main")["action"] == "report_ready"
    runtime.proceed(pending["task_id"], "user:2")
    assert runtime.prepare("git push origin main")["action"] == "allow"
    git(repo, "commit", "--allow-empty", "-qm", "done")
    assert runtime.post_commit(pending["task_id"], success=True)
    (repo / "a.py").write_text("next\n")
    git(repo, "add", ".")
    assert runtime.prepare("git push origin feature/y")["action"] == "ask_user"


def test_changed_index_cannot_reuse_report_or_disposition(runtime, repo):
    task = runtime.prepare("git push origin main")
    runtime.decide(task["task_id"], "session", "user:1", task["scope"])
    runtime.review(task["task_id"])
    runtime.proceed(task["task_id"], "user:2")
    (repo / "a.py").write_text("changed\n")
    git(repo, "add", ".")
    assert runtime.prepare("git push origin main")["action"] == "review_required"


def test_mute_does_not_need_engine_or_valid_snapshot(runtime, repo, tmp_path):
    task = runtime.prepare("git push origin main")
    runtime.decide(task["task_id"], "mute", "user:1", task["scope"])
    runtime.ocr.command = ["missing-engine"]
    (repo / "link").symlink_to(tmp_path / "private")
    git(repo, "add", "link")
    assert runtime.prepare("git push origin main")["action"] == "allow"


def test_concurrent_review_is_single_flight(runtime, tmp_path):
    task = runtime.prepare("git push origin main")
    runtime.decide(task["task_id"], "once", "user:1", task["scope"])
    results = []
    def run():
        try:
            results.append(runtime.review(task["task_id"]))
        except ValueError as error:
            results.append(str(error))
    jobs = [threading.Thread(target=run) for _ in range(2)]
    for job in jobs:
        job.start()
    for job in jobs:
        job.join(10)
    assert (tmp_path / "calls").read_text().splitlines() == ["review"]
    assert any(isinstance(result, dict) and result.get("execution_status") == "success" for result in results)


def test_cancel_stops_running_review_and_late_write(runtime, tmp_path):
    runtime.ocr.environment["FIXTURE_DELAY"] = "5"
    task = runtime.prepare("git push origin main")
    runtime.decide(task["task_id"], "once", "user:1", task["scope"])
    reports = []
    job = threading.Thread(target=lambda: reports.append(runtime.review(task["task_id"])))
    job.start()
    for _ in range(100):
        if (tmp_path / "calls").exists():
            break
        time.sleep(.03)
    runtime.reset("user:2")
    job.join(3)
    assert not job.is_alive()
    assert reports[0]["execution_status"] == "cancelled"
    assert runtime.prepare("git push origin main")["action"] == "ask_user"


def test_explicit_recovery_quarantines_only_session_state(runtime):
    runtime.prepare("git push origin main")
    runtime.store.path.write_text("broken")
    with pytest.raises(ValueError, match="corrupt_state"):
        runtime.prepare("git push origin main")
    restored = runtime.recover("user:1", mute=True)
    assert restored["preference"] == "MUTED"
    assert runtime.prepare("git push origin main")["action"] == "allow"


def test_unknown_protocol_rejected_before_mutation(runtime):
    api = importlib.import_module("codereview_core.protocol")
    for value in [{"version": 2}, {}, {"version": 1, "host": "codex", "session": ""}]:
        with pytest.raises(ValueError):
            api.validate_request(value)


def test_endpoint_change_between_prepare_and_engine_cannot_leak(runtime, tmp_path):
    from codereview_core.engine import Endpoint
    task = runtime.prepare("git push origin main")
    runtime.decide(task["task_id"], "once", "user:1", task["scope"])
    original = runtime.ocr.configuration()
    changed = Endpoint(dict(original.public, endpoint="https://unexpected.invalid", config_digest="different"),
                       original.token, original.config_path)
    calls = []
    def configuration():
        calls.append(1)
        return original if len(calls) == 1 else changed
    runtime.ocr.configuration = configuration
    report = runtime.review(task["task_id"])
    assert report["execution_status"] == "failed"
    assert report["error"] == "engine_configuration_changed"
    assert not (tmp_path / "calls").exists()


def test_failed_engine_can_be_explicitly_retried(runtime):
    task = runtime.prepare("git push origin main")
    runtime.decide(task["task_id"], "once", "user:1", task["scope"])
    failed = runtime.review(task["task_id"], timeout=.01)
    assert failed["execution_status"] == "failed"
    success = runtime.review(task["task_id"])
    assert success["execution_status"] == "success"
