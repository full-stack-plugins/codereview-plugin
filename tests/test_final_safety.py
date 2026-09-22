"""规范中的恢复、路由与消费者负例。"""
import json
import threading
import time

import pytest

from codereview_core import consent
from codereview_core.engine import OCR, resolve
from codereview_core.hosts import handle
from test_runtime import runtime
from test_git_snapshot import git, repo


def test_running_request_returns_existing_task(runtime, tmp_path):
    task = runtime.prepare()
    runtime.decide(task["task_id"], "once", "user:1", task["scope"])
    runtime.ocr.environment["FIXTURE_DELAY"] = "1"
    result = []
    worker = threading.Thread(target=lambda: result.append(runtime.review(task["task_id"])))
    worker.start()
    for _ in range(100):
        if (tmp_path / "calls").exists():
            break
        time.sleep(.02)
    second = runtime.review(task["task_id"])
    worker.join(5)
    assert second["action"] == "running" and second["task_id"] == task["task_id"]
    assert len((tmp_path / "calls").read_text().splitlines()) == 1


def test_abandoned_run_is_explicitly_retried(runtime):
    task = runtime.prepare()
    runtime.decide(task["task_id"], "once", "user:1", task["scope"])
    with runtime.store.transaction() as state:
        old = consent.begin(state, task["task_id"])
    report = runtime.review(task["task_id"])
    assert report["execution_status"] == "success" and report["run_id"] != old["id"]


def test_cancel_ends_single_commit_authorization(runtime):
    task = runtime.prepare()
    runtime.decide(task["task_id"], "once", "user:1", task["scope"])
    runtime.cancel(task["task_id"], "user:2")
    next_task = runtime.prepare()
    assert next_task["action"] == "ask_user" and next_task["task_id"] != task["task_id"]


def test_command_workdir_is_respected(runtime, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    git(other, "init", "-q")
    payload = {"hook_event_name": "PreToolUse", "session_id": "session", "cwd": str(runtime.repo),
               "tool_input": {"cmd": "git commit -m x", "workdir": str(other)}, "tool_name": "exec_command"}
    _, output = handle("codex", payload, runtime=runtime)
    state = json.loads(output.split("\n", 1)[1])
    assert state["scope"]["worktree"] == str(other.resolve())


def test_provider_config_uses_correct_section_and_preserves_required_key(tmp_path):
    path = tmp_path / "config.json"
    config = {"provider": "anthropic", "model": "m", "providers": {"anthropic": {}}}
    path.write_text(json.dumps(config))
    env = {"ANTHROPIC_API_KEY": "fake", "ANTHROPIC_BASE_URL": "https://do-not-use.invalid"}
    endpoint = resolve(path, env)
    assert endpoint.public["endpoint"] == "https://api.anthropic.com/v1/messages"
    client = OCR(config_path=path, environment=env)
    assert client.env()["ANTHROPIC_API_KEY"] == "fake"
    assert "ANTHROPIC_BASE_URL" not in client.env()


def test_post_failure_keeps_authorization(runtime):
    task = runtime.prepare()
    runtime.decide(task["task_id"], "once", "user:1", task["scope"])
    assert not runtime.post_commit(task["task_id"], success=False)
    assert runtime.prepare()["action"] == "review_required"
