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
    """分类 Git 调用，决定钩子后续动作。

    返回的 kind 决定 hosts.handle 的行为：
    - "push":        严格 ask_user 拦截（git push 是真正外发的动作，必须 codereview 授权）
    - "commit":      仅 inject 提醒，不拦截（commit 是本地动作，host 工具链不应被错误拒）
    - "unsupported": 复杂 / 动态命令，调用方应拆分暂存或明确 skip
    - "other":       其他命令（git add / reset / status / log / checkout / branch ...），
                    完全放行，钩子连提醒都不发，避免噪音
    """
    unsupported = {"kind": "unsupported", "reason": "split_command_or_explicitly_skip"}
    if not isinstance(command, str) or len(command) > 32768:
        return unsupported
    try:
        tokens = shlex.split(command)
    except ValueError:
        return unsupported
    if not tokens:
        return {"kind": "other"}
    # 第一道闸：命令里没有任何 commit / push 语义就完全放行，
    # 不因引号、变量或管道符号把无关命令误判为 unsupported。
    if not any(("commit" in token or "push" in token) for token in tokens):
        return {"kind": "other"}
    if any(x in command for x in ("$", "`", "\n")):
        return unsupported
    # echo / printf 仅打印命令内容，不真正执行；引号里有 git commit 也不当 commit 触发。
    if tokens[0] in {"echo", "printf"} and not any(c in command for c in ";|&<>"):
        return {"kind": "other"}
    if any(c in command for c in (";", "|", "&", "<", ">")):
        return unsupported
    # 非 git 命令：除非确实含 "commit"/"push" 子串（很少见），否则直接放行。
    # 注意：用子串匹配（"commit" in t），不是精确匹配；
    # 这与 hooks 入口的早期返回一致。
    if Path(tokens[0]).name != "git":
        if any(("commit" in t or "push" in t) for t in tokens):
            return unsupported
        return {"kind": "other"}
    tokens.pop(0)
    repo = Path(cwd)
    while len(tokens) >= 2 and tokens[0] == "-C":
        repo = repo / tokens[1]
        tokens = tokens[2:]
    if not tokens:
        return {"kind": "other"}
    if tokens[0].startswith("-"):
        return unsupported
    sub = tokens.pop(0)
    # push 分支：仅识别普通 push；--force / --mirror / --tags 等都视为普通 push 走 codereview。
    if sub == "push":
        unsupported_push_opts = {
            "--all", "--mirror", "--tags", "--prune", "--atomic", "--push-option",
        }
        while tokens:
            option = tokens.pop(0)
            if option in {"-q", "--quiet", "-v", "--verbose", "-f", "--force",
                          "--force-with-lease", "--no-verify", "--no-tags", "--follow-tags",
                          "-u", "--set-upstream", "--delete", "--dry-run", "--atomic",
                          "--no-atomic", "--ipv4", "--ipv6", "--thin", "--no-thin",
                          "--receive-pack", "--exec", "--upload-pack", "--repo"}:
                continue
            if option.startswith("--receive-pack=") or option.startswith("--repo=") \
               or option.startswith("--push-option=") or option.startswith("--exec=") \
               or option.startswith("--upload-pack="):
                continue
            if option.startswith("--force-with-lease="):
                continue
            # 远程名 / 引用名（如 origin main）直接放过
            if not option.startswith("-"):
                continue
            return unsupported
        return {"kind": "push", "repo": str(repo.resolve())}
    if sub == "commit":
        while tokens:
            option = tokens.pop(0)
            if option in {"-m", "--message"}:
                if not tokens:
                    return unsupported
                tokens.pop(0)
            elif option.startswith("--message=") or (option.startswith("-m") and len(option) > 2):
                continue
            elif option in {"-q", "--quiet", "-v", "--verbose", "--no-verify", "--allow-empty"}:
                continue
            else:
                return unsupported
        return {"kind": "commit", "repo": str(repo.resolve())}
    return {"kind": "other"}


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
