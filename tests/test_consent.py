"""授权回归：错误继承、重复提醒和迟到报告不得放行。"""
import copy
import importlib

import pytest


@pytest.fixture
def api():
    try:
        return importlib.import_module("codereview_core.consent")
    except ModuleNotFoundError:
        pytest.fail("尚未实现授权内核")


@pytest.fixture
def scope():
    return {"repo": "/repo", "worktree": "/repo", "common_dir": "/repo/.git",
            "endpoint": "https://model.example/v1", "model": "review-model",
            "context_policy": "tracked-candidate", "config_digest": "config-1",
            "execution_mode": "ocr-managed"}


def test_pending_question_is_not_consent_and_retries_are_deduplicated(api, scope):
    state = api.new_session("codex", "s1")
    first = api.prepare(state, scope, "tree1", "head1")
    again = api.prepare(state, scope, "tree1", "head1")
    assert first["action"] == again["action"] == "ask_user"
    assert first["task_id"] == again["task_id"]
    assert first["notify"] is True and again["notify"] is False
    with pytest.raises(ValueError, match="not_authorized"):
        api.begin(state, first["task_id"])


def test_once_survives_retry_and_next_commit_asks_again(api, scope):
    state = api.new_session("codex", "s1")
    task = api.prepare(state, scope, "tree1", "head1")["task_id"]
    api.decide(state, task, "once", "user:1", scope)
    assert api.prepare(state, scope, "tree2", "head1")["action"] == "review_required"
    assert not api.committed(state, task, success=False, head="head2", fingerprint="tree2")
    assert api.prepare(state, scope, "tree2", "head1")["task_id"] == task
    assert api.committed(state, task, success=True, head="head2", fingerprint="tree2")
    assert api.prepare(state, scope, "tree3", "head2")["action"] == "ask_user"


def test_mute_is_session_wide_but_manual_once_does_not_unmute(api, scope):
    state = api.new_session("kimi", "s1")
    task = api.prepare(state, scope, "tree1", "head1")["task_id"]
    api.decide(state, task, "mute", "user:1", scope)
    other = dict(scope, repo="/other", worktree="/other")
    assert api.prepare(state, other, "tree2", "head2")["action"] == "allow"
    assert api.prepare(state, scope, "tree1", "head1")["notify"] is False
    api.decide(state, task, "once", "user:2", scope)
    assert api.prepare(state, scope, "tree1", "head1")["action"] == "review_required"
    api.committed(state, task, success=True, head="head2", fingerprint="tree1")
    assert api.prepare(state, scope, "tree2", "head2")["action"] == "allow"
    assert api.new_session("kimi", "s2")["preference"] == "ASK"


@pytest.mark.parametrize("field,value", [
    ("endpoint", "https://other.example/v1"), ("model", "new-model"),
    ("worktree", "/another"), ("repo", "/other"),
    ("context_policy", "all-files"), ("config_digest", "config-2"),
    ("execution_mode", "delegated"),
])
def test_auto_consent_does_not_expand_scope(api, scope, field, value):
    state = api.new_session("zcode", "s1")
    task = api.prepare(state, scope, "tree1", "head1")["task_id"]
    api.decide(state, task, "session", "user:1", scope)
    assert api.prepare(state, dict(scope, **{field: value}), "tree1", "head1")["action"] == "ask_user"


def test_auto_survives_restore_and_consumed_task(api, scope):
    state = api.new_session("codex", "s1")
    task = api.prepare(state, scope, "tree1", "head1")["task_id"]
    api.decide(state, task, "session", "user:1", scope)
    api.committed(state, task, success=True, head="head2", fingerprint="tree1")
    restored = copy.deepcopy(state)
    assert api.prepare(restored, scope, "tree2", "head2")["action"] == "review_required"


def test_report_disposition_and_staleness(api, scope):
    state = api.new_session("codex", "s1")
    task = api.prepare(state, scope, "tree1", "head1")["task_id"]
    api.decide(state, task, "once", "user:1", scope)
    token = api.begin(state, task)
    report = {"execution_status": "success", "coverage_status": "limited",
              "findings": [{"content": "SQL 风险"}], "warnings": []}
    assert api.finish(state, task, token, report)
    assert api.prepare(state, scope, "tree1", "head1")["action"] == "report_ready"
    api.proceed(state, task, "user:2")
    assert api.prepare(state, scope, "tree1", "head1")["action"] == "allow"
    assert api.prepare(state, scope, "tree2", "head1")["action"] == "review_required"
    assert not api.finish(state, task, token, report)


def test_revoke_rejects_late_result_and_stops_future_runs(api, scope):
    state = api.new_session("codex", "s1")
    task = api.prepare(state, scope, "tree1", "head1")["task_id"]
    api.decide(state, task, "session", "user:1", scope)
    token = api.begin(state, task)
    api.reset(state, "user:2")
    assert not api.finish(state, task, token, {"execution_status": "success"})
    with pytest.raises(ValueError, match="not_authorized"):
        api.begin(state, task)


def test_empty_session_or_untrusted_choice_rejected(api, scope):
    with pytest.raises(ValueError):
        api.new_session("codex", "")
    state = api.new_session("codex", "s1")
    task = api.prepare(state, scope, "tree1", "head1")["task_id"]
    for choice, source in [("pass", "user:1"), ("once", ""), ("once", "model:1")]:
        with pytest.raises(ValueError):
            api.decide(state, task, choice, source, scope)
    with pytest.raises(ValueError):
        api.decide(state, task, "once", "user:1", dict(scope, api_key="secret"))


def test_unknown_report_state_is_never_accepted(api, scope):
    state = api.new_session("codex", "s1")
    task = api.prepare(state, scope, "tree1", "head1")["task_id"]
    api.decide(state, task, "once", "user:1", scope)
    token = api.begin(state, task)
    with pytest.raises(ValueError):
        api.finish(state, task, token, {"execution_status": "passed"})


def test_skip_does_not_forge_report(api, scope):
    state = api.new_session("codex", "s1")
    task = api.prepare(state, scope, "tree1", "head1")["task_id"]
    api.skip(state, task, "user:1")
    result = api.prepare(state, scope, "tree1", "head1")
    assert result["action"] == "allow" and result["reason"] == "skipped"
    assert api.get_task(state, task)["report"] is None
