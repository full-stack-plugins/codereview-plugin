"""各宿主的快速 Hook 适配；不执行模型。"""
import json
from pathlib import Path
import shlex

from . import consent
from .cli import state_root
from .git_snapshot import classify
from .runtime import Runtime


def _command(payload):
    value = payload.get("tool_input", payload.get("toolInput", {}))
    return value.get("command", value.get("cmd")) if isinstance(value, dict) else None


def _helper(command):
    try:
        parts = shlex.split(command)
        expected = Path(__file__).resolve().parents[1] / "scripts/codereview.py"
        return (len(parts) >= 3 and Path(parts[0]).name.startswith("python")
                and Path(parts[1]).resolve() == expected
                and not any(c in command for c in ";|&<>`\n"))
    except ValueError:
        return False


def handle(host, payload, *, runtime=None):
    """返回 (退出码, 文本)；0 不代表审查通过或覆盖其他插件裁决。"""
    if not isinstance(payload, dict):
        raise ValueError("invalid_hook_payload")
    event = payload.get("hook_event_name", payload.get("hookEventName"))
    if event not in {"SessionStart", "PreToolUse", "PostToolUse", "UserPromptSubmit", "Stop"}:
        return 0, ""
    command, cwd = _command(payload), payload.get("cwd")
    tool_input = payload.get("tool_input", payload.get("toolInput", {}))
    if isinstance(tool_input, dict) and isinstance(tool_input.get("workdir"), str):
        cwd = str((Path(cwd or ".") / tool_input["workdir"]).resolve())
    session = payload.get("session_id", payload.get("sessionId"))
    if event in {"PreToolUse", "PostToolUse"}:
        if not isinstance(command, str) or _helper(command):
            return 0, ""
        if not isinstance(cwd, str) or classify(command, cwd)["kind"] == "other":
            return 0, ""
    if not session or not cwd:
        return 0, "CodeReview UNVERIFIED: 缺少稳定 session_id/cwd，不能恢复授权；仅支持显式手动审查。"
    model = payload.get("model") if isinstance(payload.get("model"), str) else None
    runtime = runtime or Runtime(state_root(), host, session, cwd, host_model=model)
    if event != "PreToolUse":
        if event == "SessionStart" and runtime.store.read()["preference"] != "MUTED":
            message = "CodeReview: 可选提交审查；使用 codereview-harness 技能，未授权不外发。实际宿主加载验收 UNVERIFIED。"
            if host == "kimi":
                return 0, message
            return 0, json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": message}})
        if event == "Stop":
            summaries = []
            with runtime.store.transaction() as state:
                if state["preference"] == "MUTED":
                    return 0, ""
                for task in state["tasks"].values():
                    report = task["report"]
                    if report and report.get("run_id") != task.get("summarized_run"):
                        summaries.append({"task_id": task["id"], "execution_status": report["execution_status"],
                                          "coverage_status": report["coverage_status"]})
                        task["summarized_run"] = report.get("run_id")
            return 0, json.dumps({"codereview_summary": summaries}) if summaries else ""
        if event == "PostToolUse":
            call = payload.get("tool_use_id", payload.get("tool_call_id", payload.get("toolUseId")))
            response = payload.get("tool_response", payload.get("toolResponse", {}))
            success = isinstance(response, dict) and type(response.get("exit_code")) is int and response["exit_code"] == 0
            if call and success:
                for task in runtime.store.read()["tasks"].values():
                    if task.get("pending_call") == call and task.get("command") == command:
                        runtime.post_commit(task["id"], success=True)
        return 0, ""
    effective_command = command
    if Path(cwd).resolve() != runtime.repo:
        parsed = classify(command, cwd)
        if parsed["kind"] == "commit":
            effective_command = "git -C " + shlex.quote(parsed["repo"]) + " commit"
    result = runtime.prepare(effective_command)
    if result["action"] == "allow":
        call = payload.get("tool_use_id", payload.get("tool_call_id", payload.get("toolUseId")))
        if call and result.get("task_id"):
            with runtime.store.transaction() as state:
                consent.get_task(state, result["task_id"])["pending_call"] = call
                consent.get_task(state, result["task_id"])["command"] = command
        return 0, ""
    context = {"version": 1, "host": host, "session": session, "repo": cwd, **result}
    return 2, ("CodeReview 暂停本次提交，未执行审查。使用 codereview-harness 编排技能处理下列状态。"
               "首次询问：仅本次审查 / 当前会话自动审查 / 本会话不再提醒。"
               "notify=false 时不要重复问同一问题，等待原决定；用户可明确 skip 当前任务。"
               "结果仅建议，不代表 FlowGuard/CodeGuard 放行。\n" + json.dumps(context, ensure_ascii=True))
