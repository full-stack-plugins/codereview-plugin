"""通过 CLI 与宿主事件边界测试，拒绝路径不依赖外部模型。"""
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_git_snapshot import git, repo
from test_runtime import runtime

ROOT = Path(__file__).resolve().parents[1]


def cli(action, request, state):
    env = os.environ.copy()
    env["CODEREVIEW_STATE_DIR"] = str(state)
    p = subprocess.run([sys.executable, str(ROOT / "scripts/codereview.py"), action],
                       input=json.dumps(request), text=True, capture_output=True, env=env)
    assert p.stdout, p.stderr
    return p.returncode, json.loads(p.stdout)


def test_cli_mute_and_new_session(repo, tmp_path):
    request = {"version": 1, "host": "codex", "session": "cli-session", "repo": str(repo),
               "command": "git commit -m x"}
    code, pending = cli("prepare", request, tmp_path / "state")
    assert code == 0 and pending["action"] == "ask_user"
    code, _ = cli("decide", dict(request, task_id=pending["task_id"], scope=pending["scope"],
                                choice="mute", source="user:1"), tmp_path / "state")
    assert code == 0
    assert cli("prepare", request, tmp_path / "state")[1]["reason"] == "muted"
    assert cli("prepare", dict(request, session="next"), tmp_path / "state")[1]["action"] == "ask_user"


def test_cli_rejects_bad_json_version_and_extra_fields(tmp_path):
    for request in [{}, {"version": 2}, {"version": 1, "api_key": "should-not-echo"}]:
        code, output = cli("prepare", request, tmp_path / "state")
        assert code == 1 and output["action"] == "error"
        assert "should-not-echo" not in json.dumps(output)


@pytest.mark.parametrize("host", ["codex", "zcode", "kimi"])
def test_hooks_pause_only_commit_then_silence_after_mute(host, runtime):
    module = importlib.import_module("codereview_core.hosts")
    payload = {"hook_event_name": "PreToolUse", "session_id": "session", "cwd": str(runtime.repo),
               "tool_name": "Bash", "tool_input": {"command": "git commit -m x"}, "tool_use_id": "call-1"}
    code, output = module.handle(host, payload, runtime=runtime)
    assert code == 2 and "codereview" in output.lower()
    task = runtime.prepare("git commit -m x")
    runtime.decide(task["task_id"], "mute", "user:1", task["scope"])
    for event in ["SessionStart", "PreToolUse", "UserPromptSubmit", "Stop"]:
        code, output = module.handle(host, dict(payload, hook_event_name=event), runtime=runtime)
        assert code == 0 and output == ""


def test_post_hook_requires_matching_call_and_actual_success(runtime):
    module = importlib.import_module("codereview_core.hosts")
    payload = {"hook_event_name": "PreToolUse", "session_id": "session", "cwd": str(runtime.repo),
               "tool_name": "Bash", "tool_input": {"command": "git commit -m x"}, "tool_use_id": "call-1"}
    module.handle("codex", payload, runtime=runtime)
    task = runtime.prepare("git commit -m x")
    runtime.skip(task["task_id"], "user:1")
    module.handle("codex", payload, runtime=runtime)
    git(runtime.repo, "commit", "-qm", "done")
    wrong = dict(payload, hook_event_name="PostToolUse", tool_use_id="other", tool_response={"exit_code": 0})
    module.handle("codex", wrong, runtime=runtime)
    assert runtime.result(task["task_id"])["status"] != "committed"
    module.handle("codex", dict(wrong, tool_use_id="call-1"), runtime=runtime)
    assert runtime.result(task["task_id"])["status"] == "committed"


def test_unrelated_and_helper_commands_do_not_prompt(runtime):
    module = importlib.import_module("codereview_core.hosts")
    for command in ["git status", "echo 'git commit'", f"python3 {ROOT}/scripts/codereview.py prepare"]:
        code, output = module.handle("codex", {"hook_event_name": "PreToolUse", "session_id": "session",
            "cwd": str(runtime.repo), "tool_name": "Bash", "tool_input": {"command": command}}, runtime=runtime)
        assert code == 0 and output == ""
