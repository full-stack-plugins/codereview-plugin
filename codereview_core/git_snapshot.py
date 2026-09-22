"""不修改源仓库的提交快照与有界命令识别。"""
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import shlex
import subprocess
import shutil
import tempfile
import unicodedata

from .consent import digest


def git_env():
    """隔离 Git 环境覆盖，禁止全局配置、替换对象及可选索引写锁。"""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_OPTIONAL_LOCKS="0", GIT_NO_REPLACE_OBJECTS="1",
               GIT_AUTHOR_NAME="CodeReview Snapshot", GIT_AUTHOR_EMAIL="snapshot@example.invalid",
               GIT_COMMITTER_NAME="CodeReview Snapshot", GIT_COMMITTER_EMAIL="snapshot@example.invalid")
    return env


def git(repo, *args, data=None, optional=False):
    """无 Shell 执行有界 Git 操作，不将 Git 原始错误或配置泄漏到输出。"""
    result = subprocess.run(["git", "--no-pager", "-c", "core.hooksPath=" + os.devnull,
                             "-c", "core.fsmonitor=false", "-c", "commit.gpgSign=false", "-C", str(repo), *args],
                            input=data, capture_output=True, env=git_env(), timeout=20)
    if result.returncode:
        if optional:
            return None
        raise ValueError("git_operation_failed:" + args[0])
    return result.stdout


def classify(command, cwd):
    """只支持已知普通提交参数；复杂命令由智能体拆解，不尝试执行解析。"""
    unsupported = {"kind": "unsupported", "reason": "split_command_or_explicitly_skip"}
    if not isinstance(command, str) or len(command) > 32768:
        return unsupported
    try:
        tokens = shlex.split(command)
    except ValueError:
        return unsupported
    if not tokens:
        return {"kind": "other"}
    # 不把任意管道/变量误当成提交。动态隐藏的 Git 调用不在可证明覆盖范围内。
    if not any("commit" in token for token in tokens):
        return {"kind": "other"}
    if any(x in command for x in ("$", "`", "\n")):
        return unsupported
    # 非动态的输出命令不因引号中的 git commit 而触发。
    if tokens[0] in {"echo", "printf"} and not any(c in command for c in ";|&<>"):
        return {"kind": "other"}
    if any(c in command for c in ";|&<>"):
        return unsupported
    if Path(tokens[0]).name != "git":
        return unsupported if any("commit" in t for t in tokens) else {"kind": "other"}
    tokens.pop(0)
    repo = Path(cwd)
    while len(tokens) >= 2 and tokens[0] == "-C":
        repo = repo / tokens[1]
        tokens = tokens[2:]
    if not tokens:
        return {"kind": "other"}
    if tokens[0].startswith("-"):
        return unsupported
    if tokens.pop(0) != "commit":
        return {"kind": "other"}
    while tokens:
        option = tokens.pop(0)
        if option in {"-m", "--message"}:
            if not tokens:
                return unsupported
            tokens.pop(0)
        elif option.startswith("--message=") or (option.startswith("-m") and len(option) > 2):
            continue
        elif option not in {"-q", "--quiet", "-v", "--verbose", "--no-verify", "--allow-empty"}:
            return unsupported
    return {"kind": "commit", "repo": str(repo.resolve())}


def _safe_path(raw):
    path = os.fsdecode(raw)
    parts = PurePosixPath(path).parts
    if (not parts or PurePosixPath(path).is_absolute() or ".." in parts
            or any(p.lower() == ".git" for p in parts) or "\\" in path):
        raise ValueError("unsafe_git_path")
    return path


def _entries(raw, index=False):
    entries = []
    names = set()
    for line in raw.split(b"\0"):
        if not line:
            continue
        meta, path = line.split(b"\t", 1)
        fields = meta.decode("ascii").split()
        if index:
            mode, oid, stage = fields
            if stage != "0":
                raise ValueError("unmerged_index")
        else:
            mode, kind, oid = fields
            if kind != "blob":
                raise ValueError("unsupported_mode")
        if mode not in {"100644", "100755"}:
            raise ValueError("unsupported_mode")
        safe = _safe_path(path)
        canonical = unicodedata.normalize("NFC", safe).casefold()
        if canonical in names:
            raise ValueError("unsafe_git_path:case_or_unicode_collision")
        names.add(canonical)
        entries.append((mode, oid, safe))
    if any(str(parent) in names for name in names for parent in PurePosixPath(name).parents if str(parent) != "."):
        raise ValueError("unsafe_git_path:file_directory_collision")
    return sorted(entries, key=lambda item: os.fsencode(item[2]))


@dataclass
class Snapshot:
    """临时候选仓库与待审合成提交。"""
    path: Path
    commit: str

    def cleanup(self, parent):
        """仅删除由本插件在指定私有父目录创建的快照。"""
        parent = Path(parent).resolve()
        root = self.path.resolve()
        marker = root / ".git/codereview-managed-snapshot"
        if (root.parent != parent or not root.name.startswith("codereview-snapshot-")
                or not marker.is_file() or root.is_symlink()):
            raise ValueError("unsafe_snapshot_cleanup")
        shutil.rmtree(root)


@dataclass
class Candidate:
    """不可变 Git 对象清单；不从工作区读取候选文件内容。"""
    repo: Path
    common_dir: str
    head: str | None
    entries: list
    base_entries: list
    blobs: dict
    fingerprint: str

    @classmethod
    def read(cls, repo, *, metadata_only=False, max_bytes=64 * 1024 * 1024, max_file_bytes=4 * 1024 * 1024, max_files=5000):
        """读取基线和索引，拒绝不能精确处理的状态。"""
        root = Path(os.fsdecode(git(repo, "rev-parse", "--show-toplevel")).strip()).resolve()
        for marker in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply"):
            location = os.fsdecode(git(root, "rev-parse", "--git-path", marker)).strip()
            if (root / location).exists():
                raise ValueError("unsupported_git_operation")
        common = os.fsdecode(git(root, "rev-parse", "--git-common-dir")).strip()
        head_raw = git(root, "rev-parse", "--verify", "HEAD", optional=True)
        head = head_raw.decode().strip() if head_raw else None
        raw = git(root, "ls-files", "--stage", "-z")
        entries = _entries(raw, index=True)
        base = _entries(git(root, "ls-tree", "-r", "-z", head)) if head else []
        if len(entries) + len(base) > max_files:
            raise ValueError("snapshot_limit:files")
        objects = sorted({e[1] for e in entries + base})
        blobs = {}
        total = 0
        if objects:
            sizes = git(root, "cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)",
                        data=("\n".join(objects) + "\n").encode()).splitlines()
            for line in sizes:
                oid, kind, size = line.decode().split()
                total += int(size)
                if kind != "blob" or int(size) > max_file_bytes or total > max_bytes:
                    raise ValueError("snapshot_limit:bytes")
                if not metadata_only:
                    blobs[oid] = git(root, "cat-file", "blob", oid)
        # 读取后再核验，防止组合到跨时刻的索引/基线。
        if raw != git(root, "ls-files", "--stage", "-z") or head_raw != git(root, "rev-parse", "--verify", "HEAD", optional=True):
            raise ValueError("git_changed_during_snapshot")
        return cls(root, str((root / common).resolve()), head, entries, base, blobs,
                   digest([head, entries]))

    @contextmanager
    def snapshot(self):
        """在独立对象库创建合成提交；所有写操作只发生在本次临时目录。"""
        with tempfile.TemporaryDirectory(prefix="codereview-snapshot-") as directory:
            root = Path(directory).resolve()
            yield self._populate(root)

    def materialize(self, parent):
        """在会话私有目录持久化候选快照，供宿主智能体完成委托审查。"""
        parent = Path(parent).resolve()
        if parent.is_symlink():
            raise ValueError("unsafe_snapshot_parent")
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        parent.chmod(0o700)
        root = Path(tempfile.mkdtemp(prefix="codereview-snapshot-", dir=parent)).resolve()
        root.chmod(0o700)
        try:
            snapshot = self._populate(root)
            (root / ".git/codereview-managed-snapshot").write_text("1\n")
            return snapshot
        except BaseException:
            shutil.rmtree(root, ignore_errors=True)
            raise

    def _populate(self, root):
        git(root, "init", "-q", "--template=")
        object_map = {oid: git(root, "hash-object", "-w", "--stdin", data=blob).decode().strip()
                      for oid, blob in self.blobs.items()}

        def tree(entries):
            git(root, "read-tree", "--empty")
            data = b"".join(f"{mode} {object_map[oid]}\t".encode() + os.fsencode(path) + b"\0"
                            for mode, oid, path in entries)
            git(root, "update-index", "-z", "--index-info", data=data)
            return git(root, "write-tree").decode().strip()

        base_tree = tree(self.base_entries)
        parent = git(root, "commit-tree", base_tree, data=b"review baseline\n").decode().strip()
        candidate_tree = tree(self.entries)
        commit = git(root, "commit-tree", candidate_tree, "-p", parent,
                     data=b"review candidate\n").decode().strip()
        git(root, "update-ref", "HEAD", commit)
        for mode, oid, path in self.entries:
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.blobs[oid])
            target.chmod(0o700 if mode == "100755" else 0o600)
        return Snapshot(root, commit)
