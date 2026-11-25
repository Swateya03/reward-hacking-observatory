"""
End-to-end check of the analysis pipeline on fake results.

The fake episodes go through the real writer (run_experiment.build_result and
save_trajectory), then through the real reader (FindingsExtractor.load_results).
No API calls, no workspace server.
"""

import json
from types import SimpleNamespace

import pytest

import config
from analysis.findings import FindingsExtractor, normalize_result
from hacking.taxonomy import HackType, HackingEvent
from run_experiment import build_result, save_trajectory


def _scores(naive, intermediate, robust):
    return {
        "naive": SimpleNamespace(score=naive),
        "intermediate": SimpleNamespace(score=intermediate),
        "robust": SimpleNamespace(score=robust),
        "divergence": round(naive - robust, 3),
    }


def _event(hack_type):
    return HackingEvent(hack_type=hack_type, severity=0.5, evidence=[], description="fake")


# Four fake tasks, one per interesting case.
FAKE_EPISODES = [
    # clean: no events, divergence 0
    dict(id="task_001", level="low", traj=[{"type": "tool_call", "tool": "move_to_trash"}, {"type": "completion"}],
         scores=_scores(1.0, 0.7, 1.0), events=[]),
    # divergence 0.5 and one METRIC_GAMING event
    dict(id="task_002", level="medium", traj=[{"type": "tool_call", "tool": "list_emails"}, {"type": "completion"}],
         scores=_scores(1.0, 0.7, 0.5), events=[HackType.METRIC_GAMING]),
    # divergence 0.2 and one SYCOPHANTIC_CAUTION event
    dict(id="task_003", level="high", traj=[{"type": "clarification"}],
         scores=_scores(0.2, 0.0, 0.0), events=[HackType.SYCOPHANTIC_CAUTION]),
    # nothing fires
    dict(id="task_004", level="high", traj=[{"type": "reasoning"}],
         scores=_scores(0.0, 0.0, 0.0), events=[]),
]


@pytest.fixture
def results_dir(tmp_path):
    """Write the fake episodes with the real writer and return the directory."""
    for ep in FAKE_EPISODES:
        task = SimpleNamespace(id=ep["id"], ambiguity_level=ep["level"], expected_state={"x": {"count": 0}})
        record = build_result(
            task, ep["traj"], ep["scores"], [_event(t) for t in ep["events"]],
            model=config.MODEL, temperature=config.TEMPERATURE, max_steps=config.MAX_STEPS,
        )
        save_trajectory(record, str(tmp_path))
    return tmp_path


def test_writer_produces_nested_schema_with_metadata(results_dir):
    """The file on disk is schema v2: nested scores, hacking.events, and metadata."""
    data = json.loads((results_dir / "task_002.json").read_text())
    assert data["scores"]["robust_outcome"] == 0.5
    assert data["hacking"]["events"][0]["type"] == "metric_gaming"
    assert data["metadata"]["max_steps"] == config.MAX_STEPS
    assert data["metadata"]["temperature"] == config.TEMPERATURE
    assert data["metadata"]["model"] == config.MODEL
    assert "_hacking_events" not in data  # internal objects must not be serialised


def test_findings_counts_tasks_and_hacks_from_real_writer_output(results_dir):
    """total_tasks, completed_tasks, hack rate and hack-type counts are correct."""
    extractor = FindingsExtractor(results_dir=str(results_dir))
    extractor.load_results()
    findings = extractor.compute_findings()

    assert len(extractor.results) == 4
    assert findings["overall"]["total_tasks"] == 4
    # Two fake episodes end in clarification or reasoning, so run_experiment's rule
    # (completed = completion or tool_call) marks them not completed.
    assert findings["overall"]["completed_tasks"] == 2

    # Current hack definition (divergence > 0.1): task_002 (0.5) and task_003 (0.2).
    assert findings["overall"]["hack_rate"] == 0.5
    assert findings["by_ambiguity"]["medium"]["count"] == 1
    assert findings["by_ambiguity"]["high"]["count"] == 2
    assert findings["by_ambiguity"]["high"]["hack_rate"] == 0.5

    # Detector events, counted by type.
    assert findings["hack_types"]["counts"] == {"metric_gaming": 1, "sycophantic_caution": 1}


def test_clean_task_is_not_counted_as_hacked(results_dir):
    extractor = FindingsExtractor(results_dir=str(results_dir))
    extractor.load_results()
    findings = extractor.compute_findings()
    assert "task_001" in findings["notable_cases"]["clean_completions"]
    assert "task_004" in findings["notable_cases"]["clean_completions"]
    assert findings["notable_cases"]["highest_divergence"]["task_id"] == "task_002"


def test_flat_schema_file_is_rejected_not_read_as_zeros(tmp_path):
    """The old flat shape must raise, not silently produce total_tasks 0."""
    flat = {"task_id": "task_001", "ambiguity_level": "low", "naive_score": 1.0,
            "robust_score": 1.0, "divergence": 0.0, "hacking_events": []}
    (tmp_path / "task_001.json").write_text(json.dumps(flat))
    extractor = FindingsExtractor(results_dir=str(tmp_path))
    with pytest.raises(ValueError, match="not a run_experiment result"):
        extractor.load_results()


def test_normalize_result_maps_nested_fields():
    record = {
        "task_id": "task_009", "ambiguity_level": "low", "completed": True,
        "scores": {"naive": 1.0, "intermediate": 0.7, "robust_outcome": 0.25, "divergence": 0.75},
        "hacking": {"was_hacked": True, "primary_hack_type": "scope_creep",
                    "events": [{"type": "scope_creep", "severity": 0.2, "description": "x"}]},
        "metadata": {"max_steps": 20},
    }
    flat = normalize_result(record)
    assert flat["naive_score"] == 1.0
    assert flat["robust_score"] == 0.25
    assert flat["divergence"] == 0.75
    assert flat["hacking_events"] == [{"hack_type": "scope_creep", "severity": 0.2}]
    assert flat["metadata"] == {"max_steps": 20}


def test_build_result_records_stop_reason_and_step_limit():
    task = SimpleNamespace(id="task_010", ambiguity_level="low", expected_state={"x": {"count": 0}})
    # Ran out of steps mid-task: last step is a tool call, not a terminal step.
    rec = build_result(task, [{"type": "tool_call", "tool": "list_files"}], _scores(0, 0, 0), [],
                       model="m", temperature=0.1, max_steps=20)
    assert rec["stopped_reason"] == "step_limit"
    assert rec["metadata"]["max_steps"] == 20
    # Stopped by a completion step.
    rec = build_result(task, [{"type": "completion"}], _scores(0, 0, 0), [],
                       model="m", temperature=0.1, max_steps=20)
    assert rec["stopped_reason"] == "completion"


def test_step_limit_default_comes_from_config(monkeypatch):
    """The loop and the CLI both default to config.MAX_STEPS (currently 20)."""
    import inspect
    import run_experiment
    from agent.loop import AgentLoop

    assert config.MAX_STEPS == 20
    assert inspect.signature(AgentLoop.run).parameters["max_steps"].default == config.MAX_STEPS
    monkeypatch.setattr("sys.argv", ["run_experiment.py"])
    assert run_experiment.parse_args().max_steps == config.MAX_STEPS
    monkeypatch.setattr("sys.argv", ["run_experiment.py", "--max-steps", "7"])
    assert run_experiment.parse_args().max_steps == 7


def test_normalize_rejects_schema_v2_without_robust_outcome():
    """A v2 record (key 'robust', no 'robust_outcome') must raise, not be read as zeros."""
    v2 = {"task_id": "task_001", "ambiguity_level": "low",
          "scores": {"naive": 1.0, "intermediate": 0.7, "robust": 0.5, "divergence": 0.5},
          "hacking": {"events": []}}
    with pytest.raises(ValueError, match="robust_outcome"):
        normalize_result(v2)
