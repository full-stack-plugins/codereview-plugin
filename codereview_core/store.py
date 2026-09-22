"""仓库外的原子状态存储。"""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import tempfile
import time

from .consent import digest, new_session, validate_scope


class Store:
    """POSIX 私有目录中的会话 JSON；短事务锁不跨越模型调用。"""

    def __init__(self, root, host, session):
        self.initial = new_session(host, session)
        self.root = Path(root).expanduser().absolute()
        if self.root.is_symlink():
            raise ValueError("unsafe_state_path")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.stat().st_uid != os.getuid():
            raise ValueError("unsafe_state_owner")
        self.root.chmod(0o700)
        self.path = self.root / (digest([host, session]) + ".json")

    def _load(self):
        if self.path.is_symlink():
            raise ValueError("unsafe_state_path")
        if not self.path.exists():
            return new_session(self.initial["host"], self.initial["session"])
        try:
            if self.path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("state_too_large")
            state = json.loads(self.path.read_text())
            if (set(state) != set(self.initial) or state["version"] != 1
                    or state["host"] != self.initial["host"]
                    or state["session"] != self.initial["session"]
                    or state["preference"] not in {"ASK", "AUTO_REVIEW", "MUTED"}
                    or type(state["revision"]) is not int
                    or type(state["epoch"]) is not int
                    or not isinstance(state["auto_scopes"], list)
                    or not isinstance(state["tasks"], dict)):
                raise ValueError("invalid_state")
            for task in state["tasks"].values():
                validate_scope(task["scope"])
                if task["scope_id"] != digest(task["scope"]):
                    raise ValueError("invalid_scope_digest")
                if not {"id", "status", "authorized", "fingerprint", "head", "run", "report",
                        "source", "notified", "disposition"}.issubset(task):
                    raise ValueError("invalid_task")
                if type(task["authorized"]) is not bool or type(task["notified"]) is not bool:
                    raise ValueError("invalid_task_types")
                if task["status"] not in {"pending_choice", "authorized", "reviewing", "completed",
                                           "failed", "skipped", "committed", "cancelled"}:
                    raise ValueError("invalid_task_status")
            return state
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise ValueError("corrupt_state: use explicit recovery; no consent inferred") from exc

    @contextmanager
    def lock(self, name="session", timeout=2):
        """非阻塞尝试互斥，超时后由调用方恢复，避免 Hook 无限等待。"""
        path = self.root / (digest([self.path.name, name]) + ".lock")
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            deadline = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise ValueError("state_busy")
                    time.sleep(0.01)
            yield
        finally:
            os.close(fd)

    def read(self):
        """读取一致快照，不增加 revision。"""
        with self.lock():
            return self._load()

    @contextmanager
    def transaction(self, expected_revision=None):
        """异常自动回滚；成功时 fsync 后原子替换。"""
        with self.lock():
            state = self._load()
            revision = state["revision"]
            if expected_revision is not None and expected_revision != revision:
                raise ValueError("revision_conflict")
            yield state
            state["revision"] = revision + 1
            data = json.dumps(state, ensure_ascii=True).encode()
            if len(data) > 8 * 1024 * 1024:
                raise ValueError("state_too_large")
            fd, temporary = tempfile.mkstemp(prefix=".state-", dir=self.root)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
