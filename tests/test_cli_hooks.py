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
    """CLI prepare 对 push 走 ask_user，对 commit 走 remind，对其他命令直接 allow。"""
    request = {"version": 1, "host": "codex", "session": "cli-session", "repo": str(repo),
               "command": "git push origin main"}
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
def test_hooks_remind_commit_and_pause_push_then_silence_after_mute(host, runtime):
    """commit 是本地动作：仅 inject 提醒（return 0 + additionalContext），不阻塞；
    push 是外发动作：必须 ask_user 拦截（return 2）；
    MUTED 后两者都不再触发提醒。
    """
    module = importlib.import_module("codereview_core.hosts")
    # commit：return 0 + inject 上下文
    commit_payload = {"hook_event_name": "PreToolUse", "session_id": "session",
                      "cwd": str(runtime.repo), "tool_name": "Bash",
                      "tool_input": {"command": "git commit -m x"}, "tool_use_id": "call-1"}
    code, output = module.handle(host, commit_payload, runtime=runtime)
    assert code == 0
    assert "commit" in output.lower()
    parsed = json.loads(output)
    assert "hookSpecificOutput" in parsed
    # push：return 2 + ask_user
    push_payload = {"hook_event_name": "PreToolUse", "session_id": "session",
                    "cwd": str(runtime.repo), "tool_name": "Bash",
                    "tool_input": {"command": "git push origin main"}, "tool_use_id": "call-2"}
    code, output = module.handle(host, push_payload, runtime=runtime)
    assert code == 2
    assert "push" in output.lower()
    # MUTED：push 任务设为 mute 后，所有事件静默
    push_task = runtime.prepare("git push origin main")
    runtime.decide(push_task["task_id"], "mute", "user:1", push_task["scope"])
    for event in ["SessionStart", "PreToolUse", "UserPromptSubmit", "Stop"]:
        code, output = module.handle(host,
                                     dict(commit_payload, hook_event_name=event),
                                     runtime=runtime)
        assert code == 0 and output == ""


def test_post_hook_requires_matching_call_and_actual_success(runtime):
    """push 授权 → review → proceed → PreToolUse allow 并记录 pending_call；
    PostToolUse 必须在 call_id 匹配且实际 HEAD 前进后才能把 task 标为 committed。"""
    module = importlib.import_module("codereview_core.hosts")
    push_payload = {"hook_event_name": "PreToolUse", "session_id": "session",
                    "cwd": str(runtime.repo), "tool_name": "Bash",
                    "tool_input": {"command": "git push origin main"}, "tool_use_id": "call-1"}
    # 完整授权链：decide once → review → proceed
    task = runtime.prepare("git push origin main")
    runtime.decide(task["task_id"], "once", "user:1", task["scope"])
    report = runtime.review(task["task_id"])
    assert report["execution_status"] == "success"
    runtime.proceed(task["task_id"], "user:2")
    code, output = module.handle("codex", push_payload, runtime=runtime)
    # proceed 后 prepare→allow；hooks.handle 也应 allow（return 0）并记录 pending_call
    assert code == 0, output
    # 模拟 push 成功：HEAD 前进（没有 remote，用 --allow-empty 推进 HEAD）
    git(runtime.repo, "commit", "--allow-empty", "-qm", "done")
    wrong = dict(push_payload, hook_event_name="PostToolUse", tool_use_id="other", tool_response={"exit_code": 0})
    module.handle("codex", wrong, runtime=runtime)
    assert runtime.result(task["task_id"])["status"] != "committed"
    module.handle("codex", dict(wrong, tool_use_id="call-1"), runtime=runtime)
    assert runtime.result(task["task_id"])["status"] == "committed"


def test_unrelated_and_helper_commands_do_not_prompt(runtime):
    """任何不是 commit / push 的命令都不应触发 codereview 提醒或拦截。"""
    module = importlib.import_module("codereview_core.hosts")
    for command in ["git status", "echo 'git commit'", "echo 'git push'",
                    f"python3 {ROOT}/scripts/codereview.py prepare"]:
        code, output = module.handle("codex", {"hook_event_name": "PreToolUse", "session_id": "session",
            "cwd": str(runtime.repo), "tool_name": "Bash", "tool_input": {"command": command}}, runtime=runtime)
        assert code == 0 and output == "", (command, code, output)

def test_classify_routes_commit_push_and_others(repo):
    """classify 三分流：commit / push / other；复合与动态命令 unsupported。"""
    from codereview_core.git_snapshot import classify
    assert classify("git commit -m x", repo)["kind"] == "commit"
    assert classify("git push origin main", repo)["kind"] == "push"
    assert classify("git push --force-with-lease", repo)["kind"] == "push"
    for command in ["git status", "git add .", "git reset HEAD", "git log --oneline",
                    "git checkout main", "git branch -a", "git fetch origin",
                    "git stash", "git tag v1.0", "git rev-parse HEAD",
                    "ls | head", "echo $PATH", "npm test; npm run lint"]:
        assert classify(command, repo)["kind"] == "other", (command, classify(command, repo))
    for command in ["git commit -m $(touch x)", "git push --mirror origin",
                    "git push --all", "sh -c 'git commit -m x'"]:
        assert classify(command, repo)["kind"] == "unsupported", (command, classify(command, repo))


def test_commit_inject_reminder_and_push_blocks_with_context(runtime):
    """hosts.handle 语义：commit return 0 + additionalContext；push return 2 + ask_user 上下文。"""
    module = importlib.import_module("codereview_core.hosts")
    commit = {"hook_event_name": "PreToolUse", "session_id": "session", "cwd": str(runtime.repo),
              "tool_name": "Bash", "tool_input": {"command": "git commit -m 'fix'"}, "tool_use_id": "c1"}
    code, output = module.handle("codex", commit, runtime=runtime)
    assert code == 0
    parsed = json.loads(output)
    assert parsed["hookSpecificOutput"]["additionalContext"].find("未拦截") > 0
    push = dict(commit, tool_input={"command": "git push origin main"}, tool_use_id="p1")
    code, output = module.handle("codex", push, runtime=runtime)
    assert code == 2
    context = json.loads(output.split("\n", 1)[1])
    assert context["action"] == "ask_user"
