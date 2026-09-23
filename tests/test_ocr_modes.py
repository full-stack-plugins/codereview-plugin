"""OCR 正式双模式接口的离线契约测试。"""
import json
import os
from pathlib import Path
import sys

import pytest

from test_git_snapshot import git, repo


def fixture_command():
    return [sys.executable, str(Path(__file__).parent / "fixtures/ocr_v112_process.py")]


def write_config(path):
    path.write_text(json.dumps({"llm": {
        "url": "https://review.example/v1/messages",
        "auth_token": "DO-NOT-PRINT",
        "model": "review-model",
        "use_anthropic": True,
    }}))


def test_capabilities_do_not_require_llm_configuration(tmp_path):
    from codereview_core.engine import OCR

    capabilities = OCR(fixture_command(), config_path=tmp_path / "missing.json",
                       environment={}).capabilities(tmp_path)

    assert capabilities == {
        "version": "1.12.9",
        "delegated": True,
        "managed": True,
    }


def test_delegated_scope_discloses_host_without_ocr_llm_config(tmp_path):
    from codereview_core.engine import OCR

    scope = OCR(fixture_command(), config_path=tmp_path / "missing.json",
                environment={}).scope("delegated", host="codex", host_model="gpt-test")

    assert scope["execution_mode"] == "delegated"
    assert scope["endpoint"] == "host-agent://codex"
    assert scope["model"] == "gpt-test"
    assert "protocol" not in scope


def test_managed_scope_still_resolves_explicit_endpoint(tmp_path):
    from codereview_core.engine import OCR

    config = tmp_path / "config.json"
    write_config(config)
    scope = OCR(fixture_command(), config_path=config, environment={}).scope(
        "ocr-managed", host="codex", host_model="ignored")

    assert scope["execution_mode"] == "ocr-managed"
    assert scope["endpoint"] == "https://review.example/v1/messages"
    assert scope["model"] == "review-model"


def test_delegate_plan_uses_preview_and_rule_contract(tmp_path):
    from codereview_core.engine import OCR

    snapshot = type("Snapshot", (), {"path": tmp_path, "commit": "a" * 40})()
    plan = OCR(fixture_command(), config_path=tmp_path / "missing.json",
               environment={}).delegate(snapshot)

    assert plan["engine_version"] == "1.12.9"
    assert plan["reviewable_files"] == [{"path": "a.py", "status": "modified",
                                         "insertions": 1, "deletions": 1}]
    assert plan["rule_groups"][0]["files"] == ["a.py"]
    assert plan["coverage_required"] == ["a.py"]


def test_managed_review_reads_private_output_file_not_stdout(tmp_path):
    from codereview_core.engine import OCR

    config = tmp_path / "config.json"
    write_config(config)
    marker = tmp_path / "args.json"
    environment = {"OCR_TEST_ARGS_FILE": str(marker)}
    ocr = OCR(fixture_command(), config_path=config, environment=environment)
    endpoint = ocr.configuration()
    snapshot = type("Snapshot", (), {"path": tmp_path, "commit": "b" * 40})()
    report = ocr.review_managed(snapshot, endpoint, output_dir=tmp_path / "private")

    invoked = json.loads(marker.read_text())
    assert "--output" in invoked
    assert report["execution_status"] == "success"
    assert report["engine_version"] == "1.12.9"
    assert not (tmp_path / "private").exists()


def test_delegated_runtime_requires_complete_coverage_and_cleans_snapshot(repo, tmp_path):
    from codereview_core.engine import OCR
    from codereview_core.runtime import Runtime

    (repo / "a.py").write_text("candidate\n")
    git(repo, "add", ".")
    ocr = OCR(fixture_command(), config_path=tmp_path / "missing.json", environment=os.environ.copy())
    runtime = Runtime(tmp_path / "state", "codex", "session", repo, ocr=ocr,
                      execution_mode="delegated", host_model="gpt-test")
    pending = runtime.prepare("git commit -m x")
    runtime.decide(pending["task_id"], "once", "user:1", pending["scope"])

    plan = runtime.review(pending["task_id"])

    snapshot = Path(plan["snapshot_path"])
    assert plan["action"] == "delegate_review"
    assert snapshot.is_dir()
    assert runtime.result(pending["task_id"])["status"] == "reviewing"
    with pytest.raises(ValueError, match="incomplete_delegate_coverage"):
        runtime.complete_delegated(pending["task_id"], {
            "reviewed_files": [], "skipped_files": [], "findings": []})
    report = runtime.complete_delegated(pending["task_id"], {
        "reviewed_files": [{"path": "a.py", "status": "modified"}],
        "skipped_files": [],
        "findings": [{"path": "a.py", "content": "semantic risk", "start_line": 1,
                      "end_line": 1, "severity": "medium", "category": "correctness"}],
    })
    assert report["execution_status"] == "success"
    assert report["coverage_status"] == "limited"
    assert report["execution_mode"] == "delegated"
    assert not snapshot.exists()


def test_candidate_change_invalidates_delegate_plan_and_cleans_snapshot(repo, tmp_path):
    from codereview_core.engine import OCR
    from codereview_core.runtime import Runtime

    (repo / "a.py").write_text("candidate\n")
    git(repo, "add", ".")
    runtime = Runtime(tmp_path / "state", "codex", "session", repo,
                      ocr=OCR(fixture_command(), config_path=tmp_path / "missing.json",
                              environment=os.environ.copy()),
                      execution_mode="delegated", host_model="gpt-test")
    pending = runtime.prepare()
    runtime.decide(pending["task_id"], "once", "user:1", pending["scope"])
    plan = runtime.review(pending["task_id"])
    snapshot = Path(plan["snapshot_path"])

    (repo / "a.py").write_text("changed\n")
    git(repo, "add", ".")
    assert runtime.prepare()["action"] == "review_required"
    assert not snapshot.exists()
    with pytest.raises(ValueError, match="delegation_not_active"):
        runtime.complete_delegated(pending["task_id"], {
            "reviewed_files": [{"path": "a.py", "status": "modified"}],
            "skipped_files": [], "findings": []})


def test_delegate_accepts_recorded_real_v1129_outputs(tmp_path):
    """真实 v1.12.9 (bccbc15) 输出样例必须可解析；夹具不得再漂移出想象 schema。"""
    from codereview_core.engine import OCR

    fixtures = Path(__file__).parent / "fixtures"
    snapshot = type("Snapshot", (), {"path": tmp_path, "commit": "a" * 40})()
    plan = OCR(fixture_command(), config_path=tmp_path / "missing.json", environment={
        "OCR_FIXTURE_PREVIEW_FILE": str(fixtures / "real_v1129_preview.json"),
        "OCR_FIXTURE_RULE_FILE": str(fixtures / "real_v1129_rule.json"),
    }).delegate(snapshot)

    assert plan["engine_version"] == "1.12.9"
    assert [item["path"] for item in plan["reviewable_files"]] == ["calc.py"]
    assert plan["rule_groups"][0]["group_id"] == 1
    assert plan["coverage_required"] == ["calc.py"]


def test_capabilities_accept_brew_and_npm_version_strings(tmp_path):
    from codereview_core.engine import OCR

    for version in ("open-code-review 1.12.9 darwin/arm64",
                    "open-code-review v1.12.9 (bccbc15) darwin/arm64"):
        capabilities = OCR(fixture_command(), config_path=tmp_path / "missing.json",
                           environment={"OCR_FIXTURE_VERSION": version}).capabilities(tmp_path)
        assert capabilities["version"] == "1.12.9"
        assert capabilities["delegated"] and capabilities["managed"]


def test_managed_normalizes_recorded_real_v1129_result(tmp_path):
    """真实 v1.12.9 result.json（status=complete）必须被 normalize 接受。"""
    from codereview_core.engine import OCR

    config = tmp_path / "config.json"
    write_config(config)
    ocr = OCR(fixture_command(), config_path=config, environment={
        "OCR_FIXTURE_RESULT_FILE": str(Path(__file__).parent / "fixtures/real_v1129_result.json"),
    })
    endpoint = ocr.configuration()
    snapshot = type("Snapshot", (), {"path": tmp_path, "commit": "b" * 40})()
    report = ocr.review_managed(snapshot, endpoint, output_dir=tmp_path / "private-result")

    assert report["execution_status"] == "success"
    assert report["files_reviewed"] == 1
    assert report["findings"][0]["path"] == "a.py"
    assert report["findings"][0]["severity"] == "low"


def test_review_requires_matching_execution_mode(repo, tmp_path):
    from codereview_core.engine import OCR
    from codereview_core.runtime import Runtime

    (repo / "a.py").write_text("candidate\n")
    git(repo, "add", ".")
    ocr = OCR(fixture_command(), config_path=tmp_path / "missing.json", environment=os.environ.copy())
    delegated = Runtime(tmp_path / "state", "codex", "session", repo, ocr=ocr,
                        execution_mode="delegated", host_model="gpt-test")
    pending = delegated.prepare()
    delegated.decide(pending["task_id"], "once", "user:1", pending["scope"])
    managed = Runtime(tmp_path / "state", "codex", "session", repo, ocr=ocr,
                      execution_mode="ocr-managed", host_model="gpt-test")
    with pytest.raises(ValueError, match="execution_mode_mismatch"):
        managed.review(pending["task_id"])
    assert delegated.result(pending["task_id"])["status"] == "authorized"


def test_delegated_rejects_enabled_telemetry_config(repo, tmp_path):
    from codereview_core.engine import OCR
    from codereview_core.runtime import Runtime

    config = tmp_path / "config.json"
    config.write_text(json.dumps({"telemetry": {"enabled": True}}))
    (repo / "a.py").write_text("candidate\n")
    git(repo, "add", ".")
    runtime = Runtime(tmp_path / "state", "codex", "session", repo,
                      ocr=OCR(fixture_command(), config_path=config, environment=os.environ.copy()),
                      execution_mode="delegated", host_model="gpt-test")
    pending = runtime.prepare()
    runtime.decide(pending["task_id"], "once", "user:1", pending["scope"])
    # 引擎侧拒绝按既定模式转为诚实失败报告，错误码保留；未调用任何引擎子进程。
    report = runtime.review(pending["task_id"])
    assert report["execution_status"] == "failed"
    assert report["error"] == "telemetry_must_be_disabled_for_review"
