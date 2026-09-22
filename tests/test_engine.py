"""引擎边界使用结构化夹具和真实子进程，不访问模型。"""
import importlib
import json
import os
import sys
import time

import pytest


def result(status="success", comments=None, warnings=None):
    return {"status": status, "comments": comments,
            "summary": {"files_reviewed": 1, "comments": len(comments or []),
                        "total_tokens": 10, "input_tokens": 8, "output_tokens": 2, "elapsed": "1s"},
            "tool_calls": {"total": 1, "by_tool": {"file_read": 1}}, "warnings": warnings or []}


@pytest.mark.parametrize("status,expected", [("success", "success"),
    ("completed_with_warnings", "partial"), ("completed_with_errors", "partial"), ("skipped", "skipped")])
def test_statuses_are_not_boolean_pass(status, expected):
    engine = importlib.import_module("codereview_core.engine")
    report = engine.normalize(json.dumps(result(status)))
    assert report["execution_status"] == expected
    assert report["coverage_status"] != "complete"
    assert "passed" not in report


@pytest.mark.parametrize("payload", ["{}", "[]", "not json", '{"status":"passed"}',
    json.dumps(result()) + '\n{"Resource":[]}', json.dumps(result(comments=[{"path": "../../secret"}]))])
def test_malformed_unknown_or_polluted_output_is_unverified(payload):
    engine = importlib.import_module("codereview_core.engine")
    with pytest.raises(ValueError):
        engine.normalize(payload)


def test_warning_even_in_success_preserves_partial_and_evidence():
    engine = importlib.import_module("codereview_core.engine")
    comment = {"path": "a.py", "content": "risk", "start_line": 1, "end_line": 2,
               "existing_code": "bad()", "suggestion_code": "good()"}
    report = engine.normalize(json.dumps(result(comments=[comment], warnings=[
        {"type": "subtask_error", "file": "b.py", "message": "timeout"}])))
    assert report["execution_status"] == "partial"
    assert report["findings"][0]["severity"] == "unknown"
    assert report["findings"][0]["existing_code"] == "bad()"


def test_config_precedence_and_no_secret_disclosure(tmp_path):
    engine = importlib.import_module("codereview_core.engine")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"llm": {"url": "https://first.example/v1/messages",
        "auth_token": "DO-NOT-PRINT", "model": "m", "use_anthropic": True}}))
    environment = {"OCR_LLM_URL": "https://second.example", "OCR_LLM_TOKEN": "OTHER", "OCR_LLM_MODEL": "n"}
    resolved = engine.resolve(config, environment)
    assert resolved.public["endpoint"] == "https://first.example/v1/messages"
    assert "DO-NOT-PRINT" not in json.dumps(resolved.public)
    assert "DO-NOT-PRINT" not in repr(resolved)


def test_unconfigured_telemetry_or_extra_destinations_are_rejected(tmp_path):
    engine = importlib.import_module("codereview_core.engine")
    path = tmp_path / "config.json"
    with pytest.raises(ValueError, match="configuration_required"):
        engine.resolve(path, {})
    path.write_text(json.dumps({"telemetry": {"enabled": True, "exporter": "otlp"}}))
    with pytest.raises(ValueError, match="telemetry"):
        engine.resolve(path, {})
    path.write_text(json.dumps({"llm": {"url": "https://host/v1", "auth_token": "secret",
        "model": "m", "extra_headers": {"X-Proxy": "x"}}}))
    with pytest.raises(ValueError, match="unsupported"):
        engine.resolve(path, {})


def test_process_timeout_output_limit_and_cancel(tmp_path):
    engine = importlib.import_module("codereview_core.engine")
    for code, kwargs, error in [
        ("import time; time.sleep(5)", {"timeout": .05}, "timeout"),
        ("print('x'*10000)", {"max_bytes": 100}, "output_limit"),
        ("import time; time.sleep(5)", {"cancelled": lambda: True}, "cancelled"),
    ]:
        started = time.monotonic()
        with pytest.raises(ValueError, match=error):
            engine.run_process([sys.executable, "-c", code], tmp_path, os.environ.copy(), **kwargs)
        assert time.monotonic() - started < 3
    outcome = engine.run_process([sys.executable, "-c", "print('ok')"], tmp_path, os.environ.copy())
    assert outcome == (0, "ok\n", "")
