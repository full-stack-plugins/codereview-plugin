"""无 I/O 的授权状态机。"""
import copy
import hashlib
import json
import time
import uuid
from urllib.parse import urlsplit


SCOPE_FIELDS = {"repo", "worktree", "common_dir", "endpoint", "model",
                "context_policy", "config_digest", "execution_mode"}
RESULT_STATES = {"success", "partial", "failed", "skipped", "cancelled"}


def digest(value):
    """生成稳定的范围/内容摘要。"""
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def validate_scope(scope):
    """拒绝额外字段，防止密钥被当作授权范围存储。"""
    if not isinstance(scope, dict) or set(scope) != SCOPE_FIELDS:
        raise ValueError("invalid_scope")
    if any(not isinstance(v, str) or not v.strip() for v in scope.values()):
        raise ValueError("invalid_scope")
    endpoint = urlsplit(scope["endpoint"])
    if endpoint.scheme not in {"http", "https", "host-agent"} or not endpoint.hostname:
        raise ValueError("invalid_endpoint")
    if endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
        raise ValueError("endpoint_must_not_contain_credentials")
    return scope


def user_event(source):
    """校验受信任宿主传入的用户事件引用；不是防伪签名。"""
    if not isinstance(source, str) or not source.startswith("user:") or len(source) <= 5:
        raise ValueError("user_event_required")
    if len(source) > 200:
        raise ValueError("user_event_too_long")
    return source


def new_session(host, session):
    """创建无授权的新会话。"""
    if host not in {"codex", "zcode", "kimi"} or not isinstance(session, str) or not session.strip():
        raise ValueError("stable_session_required")
    return {"version": 1, "host": host, "session": session, "revision": 0,
            "epoch": 0, "preference": "ASK", "auto_scopes": [], "tasks": {}}


def get_task(state, task_id):
    """查找当前会话的任务，禁止跨会话引用。"""
    for task in state["tasks"].values():
        if task["id"] == task_id:
            return task
    raise ValueError("task_not_found")


def _clear_evidence(task):
    task.update(report=None, disposition=None, run=None, delegation=None)


def prepare(state, scope, fingerprint, head):
    """复用逻辑任务，返回智能体下一步，不执行任何外部操作。"""
    validate_scope(scope)
    key = digest([scope["repo"], scope["worktree"], scope["common_dir"]])
    scope_id = digest(scope)
    task = state["tasks"].get(key)
    if task is None or task["status"] in {"committed", "cancelled"}:
        task = {"id": uuid.uuid4().hex, "scope": copy.deepcopy(scope), "scope_id": scope_id,
                "fingerprint": fingerprint, "head": head, "status": "pending_choice",
                "authorized": False, "source": None, "notified": False,
                "report": None, "disposition": None, "run": None, "delegation": None}
        state["tasks"][key] = task
    if task["scope_id"] != scope_id:
        task.update(scope=copy.deepcopy(scope), scope_id=scope_id, authorized=False,
                    source=None, notified=False, status="pending_choice")
        _clear_evidence(task)
    if (task["fingerprint"], task["head"]) != (fingerprint, head):
        task.update(fingerprint=fingerprint, head=head,
                    status="authorized" if task["authorized"] else "pending_choice")
        _clear_evidence(task)
    # 单次手动审查优先于会话静默，但不会更改该偏好。
    if not task["authorized"] and state["preference"] == "MUTED":
        return _answer(task, "allow", "muted")
    if task["status"] == "skipped":
        return _answer(task, "allow", "skipped")
    if not task["authorized"] and scope_id in state["auto_scopes"]:
        task.update(authorized=True, status="authorized", source="session_grant")
    if not task["authorized"]:
        notify = not task["notified"]
        task["notified"] = True
        return _answer(task, "ask_user", "consent_required", notify)
    if task["run"]:
        return _answer(task, "running", "review_in_progress")
    if task["report"]:
        if task["disposition"] == "proceed":
            return _answer(task, "allow", "user_proceeded")
        return _answer(task, "report_ready", "review_result_requires_acknowledgement")
    return _answer(task, "review_required", "authorized")


def _answer(task, action, reason, notify=False):
    return {"version": 1, "action": action, "reason": reason,
            "task_id": task["id"], "notify": notify, "scope": task["scope"],
            "fingerprint": task["fingerprint"]}


def decide(state, task_id, choice, source, disclosed_scope):
    """记录用户决定，拒绝陈旧披露范围。"""
    user_event(source)
    validate_scope(disclosed_scope)
    if choice not in {"once", "session", "mute"}:
        raise ValueError("invalid_choice")
    task = get_task(state, task_id)
    if task["status"] in {"committed", "cancelled"}:
        raise ValueError("task_closed")
    if digest(disclosed_scope) != task["scope_id"]:
        raise ValueError("stale_disclosure")
    if choice == "mute":
        reset(state, source, preference="MUTED")
        skip(state, task_id, source)
        return
    task.update(authorized=True, source=source, status="authorized", notified=True)
    _clear_evidence(task)
    if choice == "session":
        state["preference"] = "AUTO_REVIEW"
        if task["scope_id"] not in state["auto_scopes"]:
            state["auto_scopes"].append(task["scope_id"])


def begin(state, task_id):
    """发放单次运行令牌；并发互斥由状态存储事务保护。"""
    task = get_task(state, task_id)
    if not task["authorized"] or task["status"] in {"committed", "cancelled", "skipped"}:
        raise ValueError("not_authorized")
    if task["run"]:
        raise ValueError("already_running")
    token = {"id": uuid.uuid4().hex, "epoch": state["epoch"],
             "fingerprint": task["fingerprint"], "scope_id": task["scope_id"],
             "started_at": time.time()}
    task.update(run=token, status="reviewing", report=None, disposition=None)
    return copy.deepcopy(token)


def finish(state, task_id, token, report):
    """仅当前有效令牌可以写入结果，撤销/变更后的迟到报告被丢弃。"""
    task = get_task(state, task_id)
    if not task["authorized"] or task["run"] != token or token["epoch"] != state["epoch"]:
        return False
    if not isinstance(report, dict) or report.get("execution_status") not in RESULT_STATES:
        raise ValueError("invalid_report_status")
    task.update(report=copy.deepcopy(report), run=None,
                status="completed" if report["execution_status"] == "success" else "failed")
    return True


def proceed(state, task_id, source):
    """用户接受当前报告后继续；不将报告改写成通过。"""
    user_event(source)
    task = get_task(state, task_id)
    if not task["report"]:
        raise ValueError("report_required")
    task.update(disposition="proceed", disposition_source=source)


def skip(state, task_id, source):
    """跳过当前可选审查，不产生伪造报告。"""
    user_event(source)
    task = get_task(state, task_id)
    task.update(authorized=False, status="skipped", run=None, delegation=None,
                disposition="skip", disposition_source=source)


def reset(state, source, preference="ASK"):
    """撤销所有授权，迟到报告因 epoch 改变失效。"""
    user_event(source)
    if preference not in {"ASK", "MUTED"}:
        raise ValueError("invalid_preference")
    state.update(epoch=state["epoch"] + 1, preference=preference, auto_scopes=[])
    for task in state["tasks"].values():
        task.update(authorized=False, run=None, notified=False, delegation=None)
        if task["status"] not in {"committed", "cancelled"}:
            task.update(status="pending_choice", disposition=None)


def committed(state, task_id, *, success, head, fingerprint):
    """仅调用方验证成功及候选内容一致时关闭任务。"""
    task = get_task(state, task_id)
    if success is not True or not head or head == task["head"] or fingerprint != task["fingerprint"]:
        return False
    task.update(status="committed", authorized=False, run=None, delegation=None, committed_head=head)
    return True
