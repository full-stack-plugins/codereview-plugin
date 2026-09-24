"""交付前的负向边界和真实 Git 回归。"""
import json
from pathlib import Path

import pytest

from codereview_core import consent
from codereview_core.engine import resolve
from codereview_core.git_snapshot import Candidate, classify, _safe_path
from codereview_core.hosts import handle
from codereview_core.runtime import Runtime
from test_git_snapshot import git, repo
from test_runtime import runtime


@pytest.mark.parametrize("command", ["python3 -c 'print(1)' && git status", "echo $PATH", "ls | head", "npm test; npm run lint"])
def test_unrelated_shell_composition_not_intercepted(command, repo):
    assert classify(command, repo)["kind"] == "other"


def test_manual_after_mute_restores_no_automatic_reminders(runtime):
    task = runtime.prepare("git push origin main")
    runtime.decide(task["task_id"], "mute", "user:1", task["scope"])
    manual = runtime.prepare("git push origin main", manual=True)
    assert manual["task_id"] == task["task_id"]
    runtime.decide(manual["task_id"], "once", "user:2", manual["scope"])
    assert runtime.review(manual["task_id"])["execution_status"] == "success"
    assert runtime.store.read()["preference"] == "MUTED"


def test_state_directory_rejected_before_creation(repo):
    target = repo / "private-state"
    with pytest.raises(ValueError, match="outside_repository"):
        Runtime(target, "codex", "session", repo)
    assert not target.exists()


def test_prepare_does_not_materialize_blob_content(runtime, monkeypatch):
    import codereview_core.git_snapshot as module
    original = module.git
    def guard(repo, *args, **kwargs):
        assert args[:2] != ("cat-file", "blob")
        return original(repo, *args, **kwargs)
    monkeypatch.setattr(module, "git", guard)
    assert runtime.prepare("git push origin main")["action"] == "ask_user"


def test_cleanup_revokes_only_current_session_reports(runtime):
    task = runtime.prepare("git push origin main")
    runtime.decide(task["task_id"], "once", "user:1", task["scope"])
    runtime.review(task["task_id"])
    other = Runtime(runtime.store.root, "kimi", "other", runtime.repo, ocr=runtime.ocr)
    other.prepare("git push origin main")
    data = other.store.path.read_bytes()
    runtime.cleanup("user:2")
    assert runtime.store.read()["tasks"] == {}
    assert other.store.path.read_bytes() == data
    assert git(runtime.repo, "status", "--porcelain")


def test_snapshot_rename_delete_nested_and_exception_cleanup(repo):
    (repo / "a.py").unlink()
    (repo / "a").mkdir()
    (repo / "a/x.py").write_text("nested")
    (repo / "a.txt").write_text("file before slash in byte order")
    git(repo, "add", "-A")
    candidate = Candidate.read(repo)
    with pytest.raises(RuntimeError):
        with candidate.snapshot() as snapshot:
            location = snapshot.path
            assert not (location / "a.py").exists()
            assert (location / "a/x.py").read_text() == "nested"
            raise RuntimeError("cancel")
    assert not location.exists()
    from codereview_core.git_snapshot import _entries
    git(repo, "commit", "-qm", "rename-delete")
    entries = _entries(git(repo, "ls-tree", "-r", "-z", "HEAD"))
    assert consent.digest([candidate.head, entries]) == candidate.fingerprint


@pytest.mark.parametrize("value", [{"telemetry": True}, {"llm": []}, {"provider": []}, {"providers": []}])
def test_malformed_config_is_explicit_error(tmp_path, value):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        resolve(path, {})


def test_size_and_path_limits(repo):
    with pytest.raises(ValueError, match="snapshot_limit"):
        Candidate.read(repo, max_files=0)
    for path in [b"../escape", b"/escape", b".git/config", b"dir/.GiT/config", b"a\\b"]:
        with pytest.raises(ValueError):
            _safe_path(path)


def test_missing_session_degrades_without_shared_default(runtime):
    code, result = handle("codex", {"hook_event_name": "PreToolUse", "cwd": str(runtime.repo),
         "tool_input": {"command": "git commit -m x"}}, runtime=runtime)
    assert code == 0 and "UNVERIFIED" in result
    assert not runtime.store.path.exists()
