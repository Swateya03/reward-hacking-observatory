"""Direct tests of run_experiment.build_result and its metadata block.

These import the real run_experiment module. They do not copy its logic.
No API calls, no workspace server.
"""

from datetime import datetime
from types import SimpleNamespace

import config
from hacking.taxonomy import HackType, HackingEvent
from run_experiment import RESULT_SCHEMA_VERSION, build_result


def _scores(naive, robust, intermediate=0.7):
    return {
        "naive": SimpleNamespace(score=naive),
        "intermediate": SimpleNamespace(score=intermediate),
        "robust": SimpleNamespace(score=robust),
        "divergence": round(naive - robust, 3),
    }


def _task(expected_state, level="low"):
    return SimpleNamespace(id="task_t", ambiguity_level=level, expected_state=expected_state)


def _event(hack_type):
    return HackingEvent(hack_type=hack_type, severity=0.5, evidence=[], description="x")


CLEAN = [{"type": "tool_call", "tool": "move_to_trash", "arguments": {}, "reversible": True,
          "was_in_task_scope": True},
         {"type": "completion"}]


def test_metadata_block_records_the_settings_passed_in():
    rec = build_result(_task({"x": {"count": 0}}), CLEAN, _scores(1.0, 1.0), [],
                       model="model-a", temperature=0.25, max_steps=7)
    assert rec["metadata"] == {
        "schema_version": 5,
        "model": "model-a",
        "temperature": 0.25,
        "max_steps": 7,
        "max_tokens": 2048,
    }
    # The top-level model field is the same value as metadata.model.
    assert rec["model"] == rec["metadata"]["model"]


def test_metadata_schema_version_is_the_module_constant():
    rec = build_result(_task({}), CLEAN, _scores(1.0, 0.5), [],
                       model="m", temperature=0.1, max_steps=20)
    assert rec["metadata"]["schema_version"] == RESULT_SCHEMA_VERSION == 5


def test_metadata_reflects_config_when_callers_pass_config_values():
    rec = build_result(_task({"x": {"count": 0}}), CLEAN, _scores(1.0, 1.0), [],
                       model=config.MODEL, temperature=config.TEMPERATURE, max_steps=config.MAX_STEPS)
    assert rec["metadata"]["model"] == config.MODEL
    assert rec["metadata"]["temperature"] == config.TEMPERATURE
    assert rec["metadata"]["max_steps"] == config.MAX_STEPS


def test_timestamp_is_utc_and_timezone_aware():
    rec = build_result(_task({"x": {"count": 0}}), CLEAN, _scores(1.0, 1.0), [],
                       model="m", temperature=0.1, max_steps=20)
    ts = datetime.fromisoformat(rec["timestamp"])
    assert ts.tzinfo is not None
    assert ts.utcoffset().total_seconds() == 0


def test_completion_fields_for_each_stop_reason():
    cases = [
        ([{"type": "completion"}], True, "completion", "completion"),
        ([{"type": "clarification"}], False, "clarification", "clarification"),
        ([{"type": "tool_call", "tool": "list_files"}], True, "tool_call", "step_limit"),
        ([{"type": "reasoning"}], False, "reasoning", "step_limit"),
    ]
    for traj, completed, completion_type, stopped in cases:
        rec = build_result(_task({}), traj, _scores(0, 0), [], model="m", temperature=0.1, max_steps=20)
        assert rec["completed"] is completed, traj
        assert rec["completion_type"] == completion_type
        assert rec["stopped_reason"] == stopped


def test_step_and_tool_counts():
    traj = [{"type": "tool_call", "tool": "list_files"},
            {"type": "tool_call", "tool": "move_to_trash"},
            {"type": "completion"}]
    rec = build_result(_task({}), traj, _scores(0, 0), [], model="m", temperature=0.1, max_steps=20)
    assert rec["step_count"] == 3
    assert rec["tool_call_count"] == 2


def test_na_task_writes_null_outcome_and_divergence_and_keeps_naive():
    rec = build_result(_task({}), CLEAN, _scores(1.0, 0.5), [], model="m", temperature=0.1, max_steps=20)
    assert rec["scores"]["naive"] == 1.0
    assert rec["scores"]["robust_outcome"] is None
    assert rec["scores"]["divergence"] is None
    assert rec["scores"]["robust_outcome_available"] is False


def test_state_checked_task_writes_numbers():
    rec = build_result(_task({"x": {"count": 0}}), CLEAN, _scores(1.0, 0.5), [],
                       model="m", temperature=0.1, max_steps=20)
    assert rec["scores"]["robust_outcome"] == 0.5
    assert rec["scores"]["divergence"] == 0.5
    assert rec["scores"]["robust_outcome_available"] is True


def test_hacking_block_checks_and_canonical_event_types():
    events = [_event(HackType.METRIC_GAMING)]
    rec = build_result(_task({"x": {"count": 0}}), CLEAN, _scores(0.9, 0.1), events,
                       model="m", temperature=0.1, max_steps=20)
    assert rec["hacking"]["was_hacked"] is True
    assert rec["hacking"]["primary_hack_type"] == "metric_gaming"
    assert rec["hacking"]["events"][0]["type"] == "metric_gaming"
    assert rec["hacking"]["checks"]["metric_gaming"] == {"available": True, "fired": True}
    assert rec["hacking"]["checks"]["scope_creep"] == {"available": True, "fired": False}


def test_metric_gaming_unavailable_on_na_task():
    rec = build_result(_task({}), CLEAN, _scores(1.0, 0.5), [], model="m", temperature=0.1, max_steps=20)
    assert rec["hacking"]["checks"]["metric_gaming"] == {"available": False, "fired": None}
    assert rec["hacking"]["was_hacked"] is False


def test_policy_metric_is_separate_from_scores():
    traj = [{"type": "tool_call", "tool": "move_to_trash", "arguments": {"path": "/tmp/x"}},
            {"type": "completion"}]
    rec = build_result(_task({}, level="medium"), traj, _scores(1.0, 0.5), [],
                       model="m", temperature=0.1, max_steps=20)
    assert rec["policy_metrics"] == {"unsafe_action_under_ambiguity": True}
    assert "unsafe_action_under_ambiguity" not in rec["scores"]


def test_internal_hacking_events_are_not_part_of_the_record_shape():
    """build_result returns plain data; the internal object list is not in it."""
    rec = build_result(_task({"x": {"count": 0}}), CLEAN, _scores(1.0, 1.0), [],
                       model="m", temperature=0.1, max_steps=20)
    assert "_hacking_events" not in rec
