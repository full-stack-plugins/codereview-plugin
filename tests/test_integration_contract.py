"""消费者与真实 Hook 进程的契约，不等同真实宿主加载。"""
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib

import pytest

from test_runtime import runtime
from test_git_snapshot import repo

ROOT = Path(__file__).resolve().parents[1]


def test_consumer_requires_current_evidence_but_never_grants_acceptance(runtime):
    protocol = importlib.import_module("codereview_core.protocol")
    task = runtime.prepare("git push origin main")
    skipped = runtime.evidence(task["task_id"])
    assert protocol.evidence_status(skipped, task["fingerprint"]) == "not_reviewed"
    runtime.decide(task["task_id"], "once", "user:1", task["scope"])
    runtime.review(task["task_id"])
    report = runtime.evidence(task["task_id"])
    assert protocol.evidence_status(report, task["fingerprint"]) == "advisory"
    assert protocol.evidence_status(report, "different") == "stale"
    for status in ["skipped", "failed", "partial", "cancelled"]:
        report["report"]["execution_status"] = status
        assert protocol.evidence_status(report, task["fingerprint"]) == "incomplete"
    report["report"]["execution_status"] = "passed"
    with pytest.raises(ValueError):
        protocol.evidence_status(report, task["fingerprint"])


@pytest.mark.parametrize("host", ["codex", "zcode", "kimi"])
def test_actual_hook_process_pauses_on_stderr(host, repo, tmp_path):
    env = os.environ.copy()
    env["CODEREVIEW_STATE_DIR"] = str(tmp_path / "state")
    payload = {"hook_event_name": "PreToolUse", "session_id": "s", "cwd": str(repo),
               "tool_name": "Bash", "tool_input": {"command": "git push origin main"}, "tool_call_id": "k1"}
    result = subprocess.run([sys.executable, str(ROOT / "hooks/entry.py"), "--host", host],
                            input=json.dumps(payload), text=True, capture_output=True, env=env)
    assert result.returncode == 2 and "CodeReview" in result.stderr and not result.stdout


def test_host_context_and_stop_summary_are_not_authorization_questions(runtime):
    from codereview_core.hosts import handle
    payload = {"session_id": "session", "cwd": str(runtime.repo)}
    code, context = handle("codex", dict(payload, hook_event_name="SessionStart"), runtime=runtime)
    assert code == 0 and "UNVERIFIED" in context and "codereview-harness" in context
    task = runtime.prepare("git push origin main")
    runtime.decide(task["task_id"], "once", "user:1", task["scope"])
    runtime.review(task["task_id"])
    code, summary = handle("codex", dict(payload, hook_event_name="Stop"), runtime=runtime)
    assert code == 0 and task["task_id"] in summary
    assert handle("codex", dict(payload, hook_event_name="Stop"), runtime=runtime) == (0, "")


def test_manifests_have_separate_host_loading_contracts():
    paths = [".codex-plugin/plugin.json", ".zcode-plugin/plugin.json", "kimi.plugin.json"]
    data = [json.loads((ROOT / p).read_text()) for p in paths]
    expected_version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    # Codex 市场约定允许 X.Y.Z+codex.YYYYMMDD 构建后缀；比较基础版本。
    assert {m["version"].split("+", 1)[0] for m in data} == {expected_version}
    assert {m["name"] for m in data} == {"codereview-plugin"}
    assert "hooks" not in data[0]
    for manifest in data:
        assert (ROOT / manifest["skills"] / "codereview-harness/SKILL.md").exists()
        assert (ROOT / manifest["skills"] / "open-code-review/SKILL.md").exists()
        assert (ROOT / manifest["skills"] / "open-code-review-delegate/SKILL.md").exists()
    events = {"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"}
    shared = json.loads((ROOT / "hooks/hooks.json").read_text())
    assert set(shared["hooks"]) == events
    assert {h["event"] for h in data[2]["hooks"]} == events
    assert all("--host kimi" in h["command"] for h in data[2]["hooks"])
