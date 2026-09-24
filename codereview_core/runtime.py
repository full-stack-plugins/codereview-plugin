"""把授权、快照、状态与引擎组合成可恢复审查任务。"""
import copy
import os
from pathlib import Path
import uuid

from . import consent
from .engine import OCR
from .git_snapshot import Candidate, Snapshot, _entries, classify, git
from .store import Store


class Runtime:
    """用户协作式 Harness；不是防恶意调用者的权限边界。"""

    def __init__(self, state_root, host, session, repo, *, ocr=None,
                 execution_mode="delegated", host_model=None):
        self.repo = Path(repo).resolve()
        if execution_mode not in {"delegated", "ocr-managed"}:
            raise ValueError("unsupported_execution_mode")
        self.host = host
        self.execution_mode = execution_mode
        self.host_model = host_model
        # 用户误把状态目录配置在项目里时拒绝，避免审查证据进入提交。
        root = git(self.repo, "rev-parse", "--show-toplevel", optional=True)
        boundary = Path(os.fsdecode(root).strip()).resolve() if root else self.repo
        if Path(state_root).expanduser().resolve().is_relative_to(boundary):
            raise ValueError("state_directory_must_be_outside_repository")
        self.store = Store(state_root, host, session)
        self.ocr = ocr or OCR()
        self.runs_root = self.store.root / "runs"

    def _scope(self, repo=None):
        root = Path(os.fsdecode(git(repo or self.repo, "rev-parse", "--show-toplevel")).strip()).resolve()
        if self.store.root.resolve().is_relative_to(root):
            raise ValueError("state_directory_must_be_outside_repository")
        common = str((root / os.fsdecode(git(root, "rev-parse", "--git-common-dir")).strip()).resolve())
        try:
            endpoint = self.ocr.scope(self.execution_mode, host=self.host,
                                      host_model=self.host_model)
        except ValueError:
            endpoint = {"endpoint": "https://unconfigured.invalid", "model": "unconfigured",
                        "context_policy": "tracked-candidate", "config_digest": "unconfigured",
                        "execution_mode": self.execution_mode}
        return {"repo": common, "worktree": str(root), "common_dir": common,
                **{k: endpoint[k] for k in ("endpoint", "model", "context_policy",
                                             "config_digest", "execution_mode")}}

    def _delegation(self, task):
        value = task.get("delegation")
        return copy.deepcopy(value) if isinstance(value, dict) else None

    def _cleanup_delegation(self, value):
        if not value:
            return
        try:
            Snapshot(Path(value["snapshot_path"]), value["commit"]).cleanup(self.runs_root)
        except (ValueError, OSError, KeyError):
            # 不扩大删除范围；不安全路径留给显式诊断处理。
            pass

    def prepare(self, command="git push origin main", *, manual=False):
        """只准备状态，不触发引擎；静默路径不依赖引擎或快照支持。

        返回 action 含义：
        - "allow"   直接放行（普通命令或已 MUTED）
        - "remind"  本地 commit 提醒：创建 task 但不让 hooks.handle 阻塞
                    （hooks.handle 看到 action=remind 时 return 0 + inject 提醒，
                    不会触发 ask_user 分支）
        - "ask_user" / "report_ready" / "review_required" 真实 push 场景
                    完整 codereview 授权流程
        - "unsupported" 复杂 / 动态命令，调用方拆分暂存或 skip
        """
        parsed = classify(command, self.repo)
        if parsed["kind"] == "other":
            return {"version": 1, "action": "allow", "reason": "not_a_commit", "notify": False}
        # commit 是本地动作，绝不阻塞；MUTED 时连提醒都不发
        if parsed["kind"] == "commit":
            if self.store.read()["preference"] == "MUTED":
                return {"version": 1, "action": "allow", "reason": "muted", "notify": False}
            return {"version": 1, "action": "remind", "reason": "commit_reminder",
                    "kind": "commit", "notify": True}
        state = self.store.read()
        if not manual and state["preference"] == "MUTED" and not any(t["authorized"] for t in state["tasks"].values()):
            return {"version": 1, "action": "allow", "reason": "muted", "notify": False}
        scope = self._scope(parsed.get("repo"))
        unsupported = parsed["kind"] not in {"commit", "push"}
        try:
            if unsupported:
                raise ValueError("unsupported_command")
            candidate = Candidate.read(scope["worktree"], metadata_only=True)
            fingerprint, head = candidate.fingerprint, candidate.head
        except ValueError as exc:
            unsupported = True
            reason = str(exc).split(":")[0]
            head_raw = git(scope["worktree"], "rev-parse", "--verify", "HEAD", optional=True)
            head = head_raw.decode().strip() if head_raw else None
            fingerprint = consent.digest(["unsupported", command, head])
        before = [self._delegation(task) for task in state["tasks"].values()]
        with self.store.transaction() as state:
            response = consent.prepare(state, scope, fingerprint, head)
            task = consent.get_task(state, response["task_id"])
            task["command"] = command
            task["unsupported"] = unsupported
            if unsupported and response["action"] != "allow":
                response.update(action="unsupported", reason=reason, can_skip=True)
            response["configuration_ready"] = scope["config_digest"] != "unconfigured"
        live_paths = {task.get("delegation", {}).get("snapshot_path")
                      for task in self.store.read()["tasks"].values()
                      if isinstance(task.get("delegation"), dict)}
        for delegation in before:
            if delegation and delegation.get("snapshot_path") not in live_paths:
                self._cleanup_delegation(delegation)
        return response

    def decide(self, task_id, choice, source, scope):
        consent.validate_scope(scope)
        if choice != "mute" and scope.get("config_digest") == "unconfigured":
            raise ValueError("configuration_required")
        with self.store.transaction() as state:
            consent.decide(state, task_id, choice, source, scope)

    def proceed(self, task_id, source):
        with self.store.transaction() as state:
            consent.proceed(state, task_id, source)

    def skip(self, task_id, source):
        delegation = self._delegation(consent.get_task(self.store.read(), task_id))
        with self.store.transaction() as state:
            consent.skip(state, task_id, source)
        self._cleanup_delegation(delegation)

    def cancel(self, task_id, source):
        delegation = self._delegation(consent.get_task(self.store.read(), task_id))
        with self.store.transaction() as state:
            consent.skip(state, task_id, source)
            consent.get_task(state, task_id)["status"] = "cancelled"
        self._cleanup_delegation(delegation)

    def reset(self, source):
        delegations = [self._delegation(task) for task in self.store.read()["tasks"].values()]
        with self.store.transaction() as state:
            consent.reset(state, source)
        for delegation in delegations:
            self._cleanup_delegation(delegation)

    def cleanup(self, source):
        """只清除当前会话任务/报告并撤销授权；保留偏好与锁文件。"""
        delegations = [self._delegation(task) for task in self.store.read()["tasks"].values()]
        with self.store.transaction() as state:
            consent.reset(state, source, preference="MUTED" if state["preference"] == "MUTED" else "ASK")
            state["tasks"] = {}
        for delegation in delegations:
            self._cleanup_delegation(delegation)

    def result(self, task_id):
        task = consent.get_task(self.store.read(), task_id)
        return {"version": 1, "task_id": task_id, "status": task["status"],
                "report": task["report"], "disposition": task["disposition"],
                "scope": task["scope"], "fingerprint": task["fingerprint"]}

    def evidence(self, task_id):
        """只读导出当前证据；协调方自行核对作用范围和内容。"""
        state = self.store.read()
        task = consent.get_task(state, task_id)
        return {"version": 1, "producer": "codereview-plugin", "task_id": task_id,
                "host": state["host"], "session": state["session"], "scope": task["scope"],
                "fingerprint": task["fingerprint"], "baseline": task["head"],
                "preference": state["preference"], "task_status": task["status"],
                "authorization_source": task["source"], "report": task["report"],
                "user_disposition": task["disposition"],
                "disposition_source": task.get("disposition_source"),
                "skip_reason": "session_muted" if state["preference"] == "MUTED" else
                    ("user_skipped" if task["disposition"] == "skip" else None)}

    def review(self, task_id, *, timeout=600):
        try:
            return self._review(task_id, timeout=timeout)
        except ValueError as exc:
            if str(exc) != "state_busy":
                raise
            return {"version": 1, "action": "running", "task_id": task_id,
                    "reason": "existing_task_or_state_transaction"}

    def _review(self, task_id, *, timeout):
        """运行锁只保护引擎单飞；授权状态短事务可被并发撤销。"""
        with self.store.lock("run:" + task_id, timeout=0):
            task = consent.get_task(self.store.read(), task_id)
            if not task["authorized"]:
                raise ValueError("not_authorized")
            if task.get("unsupported"):
                raise ValueError("unsupported_commit")
            # 模式不一致必须显式报错；进入范围重推导会静默撤销授权并误报 not_authorized。
            if task["scope"]["execution_mode"] != self.execution_mode:
                raise ValueError("execution_mode_mismatch")
            candidate = Candidate.read(task["scope"]["worktree"])
            scope = self._scope(candidate.repo)
            with self.store.transaction() as state:
                response = consent.prepare(state, scope, candidate.fingerprint, candidate.head)
                if response["task_id"] != task_id:
                    raise ValueError("task_closed")
                task = consent.get_task(state, task_id)
                # 能取得运行锁却留下 run 表示旧进程已退出；不后台自动执行。
                if task["run"]:
                    task.update(run=None, status="failed")
                if task["report"] and task["report"]["execution_status"] == "success" and not task["report"].get("stale"):
                    return copy.deepcopy(task["report"])
                token = consent.begin(state, task_id)

            def cancelled():
                current = self.store.read()
                if current["epoch"] != token["epoch"]:
                    return True
                if not any(t["id"] == task_id for t in current["tasks"].values()):
                    return True
                active = consent.get_task(current, task_id)
                return current["epoch"] != token["epoch"] or active["run"] != token

            try:
                if consent.digest(scope) != token["scope_id"]:
                    raise ValueError("engine_configuration_changed")
                if scope["execution_mode"] == "delegated":
                    snapshot = candidate.materialize(self.runs_root)
                    try:
                        plan = self.ocr.delegate(snapshot, cancelled=cancelled,
                                                 timeout=min(timeout, 60))
                        if not plan["reviewable_files"]:
                            report = {"version": 1, "execution_status": "skipped",
                                      "coverage_status": "none", "findings": [],
                                      "warnings": [{"type": "all_files_filtered"}],
                                      "files_reviewed": 0, "engine_version": plan["engine_version"],
                                      "execution_mode": "delegated"}
                            snapshot.cleanup(self.runs_root)
                        else:
                            delegation = {**plan, "snapshot_path": str(snapshot.path),
                                          "commit": snapshot.commit}
                            with self.store.transaction() as state:
                                active = consent.get_task(state, task_id)
                                if (state["epoch"] != token["epoch"] or active["run"] != token):
                                    raise ValueError("cancelled")
                                active["delegation"] = delegation
                            return {"version": 1, "action": "delegate_review",
                                    "task_id": task_id, "run_id": token["id"], **delegation}
                    except BaseException:
                        if snapshot.path.exists():
                            self._cleanup_delegation({"snapshot_path": str(snapshot.path),
                                                      "commit": snapshot.commit})
                        raise
                else:
                    endpoint = self.ocr.configuration()
                    if any(endpoint.public[key] != scope[key] for key in
                           ("endpoint", "model", "context_policy", "config_digest")):
                        raise ValueError("engine_configuration_changed")
                    self.runs_root.mkdir(mode=0o700, parents=True, exist_ok=True)
                    output_dir = self.runs_root / ("output-" + token["id"])
                    with candidate.snapshot() as snapshot:
                        report = self.ocr.review_managed(snapshot, endpoint, output_dir=output_dir,
                                                         cancelled=cancelled, timeout=timeout)
                    report["execution_mode"] = "ocr-managed"
                report.update(run_id=token["id"], fingerprint=candidate.fingerprint,
                              baseline=candidate.head, scope=scope)
                if Candidate.read(candidate.repo, metadata_only=True).fingerprint != candidate.fingerprint:
                    report.update(execution_status="partial", stale=True)
            except (ValueError, OSError, UnicodeError) as exc:
                code = str(exc).split(":")[0] if isinstance(exc, ValueError) else "engine_unavailable"
                report = {"version": 1, "execution_status": "cancelled" if code == "cancelled" else "failed",
                          "coverage_status": "unverified", "findings": [], "warnings": [],
                          "error": code, "run_id": token["id"], "fingerprint": candidate.fingerprint}
            with self.store.transaction() as state:
                if (state["epoch"] != token["epoch"]
                        or not any(t["id"] == task_id for t in state["tasks"].values())
                        or not consent.finish(state, task_id, token, report)):
                    return {"version": 1, "execution_status": "cancelled", "coverage_status": "unverified",
                            "error": "authorization_revoked_or_content_changed"}
            return report

    def complete_delegated(self, task_id, submission):
        """校验宿主智能体逐文件覆盖后，完成仍处于同一授权范围的委托审查。"""
        if not isinstance(submission, dict) or set(submission) != {
                "reviewed_files", "skipped_files", "findings"}:
            raise ValueError("invalid_delegate_report")
        with self.store.lock("run:" + task_id, timeout=0):
            task = consent.get_task(self.store.read(), task_id)
            token = copy.deepcopy(task.get("run"))
            delegation = self._delegation(task)
            if (not task["authorized"] or not token or not delegation
                    or task["scope"].get("execution_mode") != "delegated"):
                raise ValueError("delegation_not_active")
            expected = {item["path"]: item["status"] for item in delegation["reviewable_files"]}
            reviewed = submission["reviewed_files"]
            skipped = submission["skipped_files"]
            findings = submission["findings"]
            if not all(isinstance(value, list) for value in (reviewed, skipped, findings)):
                raise ValueError("invalid_delegate_report")
            seen = {}
            for item in reviewed:
                if (not isinstance(item, dict) or set(item) != {"path", "status"}
                        or expected.get(item.get("path")) != item.get("status")):
                    raise ValueError("invalid_delegate_coverage")
                seen[item["path"]] = seen.get(item["path"], 0) + 1
            for item in skipped:
                if (not isinstance(item, dict) or set(item) != {"path", "status", "reason"}
                        or expected.get(item.get("path")) != item.get("status")
                        or not isinstance(item.get("reason"), str) or not item["reason"].strip()):
                    raise ValueError("invalid_delegate_coverage")
                seen[item["path"]] = seen.get(item["path"], 0) + 1
            if set(seen) != set(expected) or any(count != 1 for count in seen.values()):
                raise ValueError("incomplete_delegate_coverage")
            normalized = []
            reviewed_paths = {item["path"] for item in reviewed}
            for finding in findings:
                if (not isinstance(finding, dict) or set(finding) != {
                        "path", "content", "start_line", "end_line", "severity", "category"}
                        or finding.get("path") not in reviewed_paths
                        or not isinstance(finding.get("content"), str) or not finding["content"].strip()
                        or type(finding.get("start_line")) is not int
                        or type(finding.get("end_line")) is not int
                        or not 1 <= finding["start_line"] <= finding["end_line"]
                        or not isinstance(finding.get("severity"), str)
                        or not isinstance(finding.get("category"), str)):
                    raise ValueError("invalid_delegate_finding")
                normalized.append(copy.deepcopy(finding))
            if self._scope(task["scope"]["worktree"]) != task["scope"]:
                raise ValueError("engine_configuration_changed")
            current = Candidate.read(task["scope"]["worktree"], metadata_only=True)
            if current.fingerprint != token["fingerprint"]:
                raise ValueError("candidate_changed")
            report = {
                "version": 1,
                "execution_status": "partial" if skipped else "success",
                "coverage_status": "limited",
                "coverage_note": "逐文件回执完整，但语义审查仍是建议性证据，不构成安全保证。",
                "execution_mode": "delegated",
                "engine_version": delegation["engine_version"],
                "findings": normalized,
                "warnings": ([{"type": "host_files_skipped", "files": skipped}] if skipped else []),
                "files_reviewed": len(reviewed),
                "run_id": token["id"],
                "fingerprint": token["fingerprint"],
                "baseline": task["head"],
                "scope": copy.deepcopy(task["scope"]),
            }
            with self.store.transaction() as state:
                active = consent.get_task(state, task_id)
                if not consent.finish(state, task_id, token, report):
                    raise ValueError("authorization_revoked_or_content_changed")
                active["delegation"] = None
            self._cleanup_delegation(delegation)
            return report

    def post_commit(self, task_id, *, success):
        task = consent.get_task(self.store.read(), task_id)
        root = task["scope"]["worktree"]
        head_raw = git(root, "rev-parse", "--verify", "HEAD", optional=True)
        if not head_raw or success is not True:
            return False
        head = head_raw.decode().strip()
        parents = git(root, "rev-list", "--parents", "-n", "1", head).decode().split()[1:]
        if parents != ([task["head"]] if task["head"] else []):
            return False
        entries = _entries(git(root, "ls-tree", "-r", "-z", head))
        fingerprint = consent.digest([task["head"], entries])
        with self.store.transaction() as state:
            return consent.committed(state, task_id, success=success, head=head, fingerprint=fingerprint)

    def recover(self, source, *, mute=False):
        """用户明确恢复：隔离当前会话文件，不删除源码或其他会话。"""
        consent.user_event(source)
        with self.store.lock():
            if self.store.path.is_symlink():
                raise ValueError("unsafe_state_path")
            if self.store.path.exists():
                destination = self.store.path.with_suffix(".quarantine-" + uuid.uuid4().hex)
                self.store.path.rename(destination)
        with self.store.transaction() as state:
            consent.reset(state, source, preference="MUTED" if mute else "ASK")
        return self.store.read()
