"""真实多进程验证状态互斥与持久化，不模拟文件系统。"""
import importlib
import multiprocessing
import os

import pytest


def increment(path):
    from codereview_core.store import Store
    store = Store(path, "codex", "session")
    for _ in range(15):
        with store.transaction() as state:
            state["epoch"] += 1


def test_transactions_are_atomic_and_private(tmp_path):
    module = importlib.import_module("codereview_core.store")
    store = module.Store(tmp_path / "state", "codex", "session")
    with store.transaction() as state:
        state["preference"] = "MUTED"
    assert store.read()["preference"] == "MUTED"
    assert store.read()["revision"] == 1
    assert os.stat(store.path).st_mode & 0o777 == 0o600
    assert os.stat(store.root).st_mode & 0o777 == 0o700
    with pytest.raises(RuntimeError):
        with store.transaction() as state:
            state["preference"] = "ASK"
            raise RuntimeError("rollback")
    assert store.read()["preference"] == "MUTED"


def test_multiprocess_updates_do_not_get_lost(tmp_path):
    module = importlib.import_module("codereview_core.store")
    ctx = multiprocessing.get_context("spawn")
    jobs = [ctx.Process(target=increment, args=(str(tmp_path / "state"),)) for _ in range(3)]
    for job in jobs:
        job.start()
    for job in jobs:
        job.join(15)
        assert job.exitcode == 0
    assert module.Store(tmp_path / "state", "codex", "session").read()["epoch"] == 45


def test_corruption_and_version_never_create_consent(tmp_path):
    module = importlib.import_module("codereview_core.store")
    store = module.Store(tmp_path / "state", "codex", "session")
    with store.transaction():
        pass
    store.path.write_text('{"version":99,"preference":"AUTO_REVIEW"}')
    with pytest.raises(ValueError, match="corrupt_state"):
        store.read()
    assert module.Store(tmp_path / "state", "codex", "other").read()["preference"] == "ASK"


def test_optimistic_revision_and_symlink_rejection(tmp_path):
    module = importlib.import_module("codereview_core.store")
    store = module.Store(tmp_path / "state", "codex", "session")
    with store.transaction():
        pass
    with pytest.raises(ValueError, match="revision_conflict"):
        with store.transaction(expected_revision=0):
            pass
    external = tmp_path / "external"
    external.write_text("private")
    store.path.unlink()
    store.path.symlink_to(external)
    with pytest.raises(ValueError, match="unsafe_state_path"):
        store.read()
    assert external.read_text() == "private"
