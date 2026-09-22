"""版本化的 CLI 请求校验。"""
from .consent import new_session
from .consent import RESULT_STATES, validate_scope


def validate_request(value):
    """未知版本、字段、身份和缺失路径不被宽松猜测。"""
    allowed = {"version", "host", "session", "repo", "command", "task_id", "choice", "source",
               "scope", "success", "mute", "timeout", "execution_mode", "model", "report"}
    if not isinstance(value, dict) or set(value) - allowed or type(value.get("version")) is not int or value["version"] != 1:
        raise ValueError("invalid_protocol_version_or_fields")
    new_session(value.get("host"), value.get("session"))
    if not isinstance(value.get("repo"), str) or not value["repo"]:
        raise ValueError("repo_required")
    for key in ("command", "task_id", "choice", "source", "execution_mode", "model"):
        if key in value and not isinstance(value[key], str):
            raise ValueError("invalid_field_type")
    if "execution_mode" in value and value["execution_mode"] not in {"delegated", "ocr-managed"}:
        raise ValueError("unsupported_execution_mode")
    if "report" in value and not isinstance(value["report"], dict):
        raise ValueError("invalid_field_type")
    for key in ("success", "mute"):
        if key in value and type(value[key]) is not bool:
            raise ValueError("invalid_field_type")
    if "timeout" in value and (type(value["timeout"]) not in {int, float} or not 0 < value["timeout"] <= 1800):
        raise ValueError("invalid_timeout")
    return value


def evidence_status(value, fingerprint):
    """FlowGuard 参考消费者：分类证据，绝不产生流程验收/安全通过。"""
    if (not isinstance(value, dict) or value.get("version") != 1
            or value.get("producer") != "codereview-plugin"
            or not isinstance(value.get("task_id"), str)):
        raise ValueError("invalid_evidence")
    validate_scope(value.get("scope"))
    if value.get("fingerprint") != fingerprint:
        return "stale"
    report = value.get("report")
    if report is None:
        return "not_reviewed"
    if not isinstance(report, dict) or report.get("execution_status") not in RESULT_STATES:
        raise ValueError("invalid_report_status")
    if report.get("stale") or report.get("fingerprint") != fingerprint:
        return "stale"
    return "advisory" if report["execution_status"] == "success" else "incomplete"
