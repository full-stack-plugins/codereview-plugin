"""非交互 CLI；授权问题由宿主智能体展示。"""
import argparse
import json
import os
from pathlib import Path
import re
import sys

from .protocol import validate_request
from .runtime import Runtime


def state_root():
    return Path(os.environ.get("CODEREVIEW_STATE_DIR") or
                str(Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "codereview-plugin"))


def error_code(exc):
    value = str(exc).split(":")[0]
    return value if re.fullmatch(r"[a-z_]{3,80}", value) else "invalid_request_or_runtime_error"


def execute(action, request):
    request = validate_request(request)
    runtime = Runtime(state_root(), request["host"], request["session"], request["repo"],
                      execution_mode=request.get("execution_mode", "delegated"),
                      host_model=request.get("model"))
    task, source = request.get("task_id"), request.get("source")
    if action in {"prepare", "manual"}:
        # 默认命令是 push：新语义下 commit 只提醒（remind，无 task），
        # 真正进入授权/审查流程的是 push。
        return runtime.prepare(request.get("command", "git push origin main"), manual=action == "manual")
    if action == "status":
        state = runtime.store.read()
        return {"version": 1, "preference": state["preference"], "revision": state["revision"],
                "tasks": [{"task_id": t["id"], "status": t["status"]} for t in state["tasks"].values()]}
    if action == "doctor":
        capabilities = runtime.ocr.capabilities(runtime.repo)
        return {"version": 1, "action": "ready", **capabilities}
    if action == "decide":
        runtime.decide(task, request.get("choice"), source, request.get("scope"))
    elif action == "review":
        return runtime.review(task, timeout=request.get("timeout", 600))
    elif action == "complete-delegated":
        return runtime.complete_delegated(task, request.get("report"))
    elif action in {"result", "evidence"}:
        return getattr(runtime, action)(task)
    elif action in {"proceed", "skip", "cancel"}:
        getattr(runtime, action)(task, source)
    elif action in {"reset", "cleanup"}:
        getattr(runtime, action)(source)
    elif action == "recover":
        runtime.recover(source, mute=request.get("mute", False))
    elif action == "post-commit":
        return {"version": 1, "closed": runtime.post_commit(task, success=request.get("success"))}
    else:
        raise ValueError("unknown_action")
    return {"version": 1, "action": "recorded"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "manual", "status", "doctor", "decide", "review", "complete-delegated", "result",
                                            "proceed", "skip", "cancel", "reset", "cleanup", "recover", "post-commit", "evidence"])
    parser.add_argument("--request", type=Path, help="私有 JSON 请求文件；省略时读取 stdin")
    args = parser.parse_args()
    try:
        if args.request:
            with args.request.open("rb") as stream:
                raw = stream.read(65537)
        else:
            raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            raise ValueError("request_too_large")
        result = execute(args.action, json.loads(raw))
        print(json.dumps(result, ensure_ascii=True))
        return 1 if result.get("execution_status") in {"failed", "cancelled"} else 0
    except (ValueError, OSError, TypeError, KeyError, AttributeError) as exc:
        print(json.dumps({"version": 1, "action": "error", "error": error_code(exc)}))
        return 1
