"""以真实 Git 验证快照内容，而不是只验证 Git 参数。"""
import importlib
import os
from pathlib import Path
import subprocess

import pytest


def git(repo, *args, data=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_AUTHOR_NAME="Test", GIT_AUTHOR_EMAIL="test@example.invalid",
               GIT_COMMITTER_NAME="Test", GIT_COMMITTER_EMAIL="test@example.invalid")
    return subprocess.run(["git", "-C", str(repo), *args], input=data,
                          capture_output=True, check=True, env=env).stdout


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q")
    (path / "a.py").write_text("baseline\n")
    git(path, "add", ".")
    git(path, "commit", "-qm", "baseline")
    return path


def test_partial_index_snapshot_and_original_repository_unchanged(repo):
    api = importlib.import_module("codereview_core.git_snapshot")
    (repo / "a.py").write_text("staged\n")
    git(repo, "add", "a.py")
    (repo / "a.py").write_text("unstaged\n")
    (repo / "untracked.py").write_text("do not send")
    index_before = (repo / ".git/index").read_bytes()
    head_before = git(repo, "rev-parse", "HEAD")
    candidate = api.Candidate.read(repo)
    with candidate.snapshot() as snapshot:
        snapshot_path = snapshot.path
        assert (snapshot.path / "a.py").read_text() == "staged\n"
        assert not (snapshot.path / "untracked.py").exists()
        assert git(snapshot.path, "show", f"{snapshot.commit}:a.py") == b"staged\n"
        assert git(snapshot.path, "show", f"{snapshot.commit}^:a.py") == b"baseline\n"
    assert not snapshot_path.exists()
    assert git(repo, "rev-parse", "HEAD") == head_before
    assert (repo / ".git/index").read_bytes() == index_before
    assert (repo / "a.py").read_text() == "unstaged\n"


def test_first_commit_and_newline_name(tmp_path):
    api = importlib.import_module("codereview_core.git_snapshot")
    git(tmp_path, "init", "-q")
    (tmp_path / "space \n.py").write_text("new\n")
    git(tmp_path, "add", ".")
    candidate = api.Candidate.read(tmp_path)
    assert candidate.head is None
    with candidate.snapshot() as snap:
        assert git(snap.path, "ls-tree", "--name-only", snap.commit + "^") == b""
        assert (snap.path / "space \n.py").read_text() == "new\n"


def test_fingerprint_changes_on_index_and_baseline_not_worktree(repo):
    api = importlib.import_module("codereview_core.git_snapshot")
    first = api.Candidate.read(repo)
    (repo / "a.py").write_text("next\n")
    assert api.Candidate.read(repo).fingerprint == first.fingerprint
    git(repo, "add", ".")
    second = api.Candidate.read(repo)
    assert second.fingerprint != first.fingerprint
    git(repo, "commit", "-qm", "next")
    assert api.Candidate.read(repo).fingerprint != second.fingerprint


def test_symlink_submodule_conflict_and_size_are_explicit(repo, tmp_path):
    api = importlib.import_module("codereview_core.git_snapshot")
    (repo / "outside").symlink_to(tmp_path / "private")
    git(repo, "add", "outside")
    with pytest.raises(ValueError, match="unsupported_mode"):
        api.Candidate.read(repo)
    git(repo, "rm", "--cached", "outside")
    with pytest.raises(ValueError, match="snapshot_limit"):
        api.Candidate.read(repo, max_bytes=1)
    oid = git(repo, "rev-parse", "HEAD").strip().decode()
    git(repo, "update-index", "--add", "--cacheinfo", f"160000,{oid},submodule")
    with pytest.raises(ValueError, match="unsupported_mode"):
        api.Candidate.read(repo)
    git(repo, "update-index", "--force-remove", "submodule")
    blob = git(repo, "rev-parse", "HEAD:a.py").strip().decode()
    git(repo, "update-index", "--index-info", data=f"0 {'0' * 40}\ta.py\n100644 {blob} 1\ta.py\n".encode())
    with pytest.raises(ValueError, match="unmerged_index"):
        api.Candidate.read(repo)


def test_snapshot_does_not_execute_hooks_or_filters(repo):
    api = importlib.import_module("codereview_core.git_snapshot")
    sentinel = repo.parent / "executed"
    hook = repo / ".git/hooks/post-checkout"
    hook.write_text(f"#!/bin/sh\ntouch '{sentinel}'\n")
    hook.chmod(0o755)
    git(repo, "config", "filter.evil.smudge", f"touch '{sentinel}'")
    (repo / ".gitattributes").write_text("*.py filter=evil\n")
    git(repo, "add", ".gitattributes")
    with api.Candidate.read(repo).snapshot():
        assert not sentinel.exists()


@pytest.mark.parametrize("command,expected", [
    ("git commit -m '提交'", "commit"),
    ("git -C /repo commit --message=x", "commit"),
    ("echo 'git commit -m x'", "other"),
    ("git status", "other"),
    ("git add . && git commit -m x", "unsupported"),
    ("cd /repo && git commit -m x", "unsupported"),
    ("git commit -am x", "unsupported"),
    ("git commit --amend -m x", "unsupported"),
    ("git commit -- a.py", "unsupported"),
    ("sh -c 'git commit -m x'", "unsupported"),
    ("git commit -m $(touch sentinel)", "unsupported"),
    ("git -c alias.c=commit c", "unsupported"),
])
def test_commit_command_normalization(command, expected):
    api = importlib.import_module("codereview_core.git_snapshot")
    assert api.classify(command, Path("/repo"))["kind"] == expected
