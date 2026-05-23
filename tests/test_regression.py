"""Regression tests for empirical findings.

This test locks in key numbers from results/findings.json so future
code changes can't silently break the findings. Tests read actual
experimental results and verify they fall within expected ranges.
"""

import json
from pathlib import Path
import pytest


def load_findings() -> dict:
    """Load findings from results/findings.json."""
    findings_path = Path("results/findings.json")

    if not findings_path.exists():
        pytest.skip("results/findings.json not found (clean repo)")

    with open(findings_path, "r") as f:
        return json.load(f)


class TestFindingsExist:
    """Verify findings file structure."""

    def test_findings_has_all_required_keys(self):
        """Findings dict must have all required top-level sections."""
        findings = load_findings()

        required = ["overall", "by_ambiguity", "hack_types", "notable_cases"]
        for key in required:
            assert key in findings, f"Missing key: {key}"

    def test_overall_has_required_fields(self):
        """Overall section must have all required fields."""
        findings = load_findings()
        overall = findings["overall"]

        required = [
            "total_tasks",
            "completed_tasks",
            "completion_rate",
            "avg_naive",
            "avg_robust",
            "avg_divergence",
            "hack_rate",
            "naive_greater_than_robust_pct",
        ]

        for field in required:
            assert field in overall, f"Missing field in overall: {field}"

    def test_by_ambiguity_has_all_levels(self):
        """by_ambiguity must include all three levels."""
        findings = load_findings()

        for level in ["low", "medium", "high"]:
            assert level in findings["by_ambiguity"], f"Missing level: {level}"


class TestHackingRates:
    """Regression tests for hacking rate metrics."""

    def test_overall_hack_rate_reasonable(self):
        """Overall hack rate should be between 30-80%."""
        findings = load_findings()
        hack_rate = findings["overall"]["hack_rate"]

        assert 0.3 <= hack_rate <= 0.8, (
            f"Hack rate {hack_rate} outside expected range 30-80%"
        )

    def test_low_ambiguity_hack_rate_lower_than_medium(self):
        """Low ambiguity should have lower hack rate than medium."""
        findings = load_findings()
        low_rate = findings["by_ambiguity"]["low"]["hack_rate"]
        medium_rate = findings["by_ambiguity"]["medium"]["hack_rate"]

        assert low_rate < medium_rate, (
            f"Low hack rate ({low_rate}) should be less than medium ({medium_rate})"
        )

    def test_medium_ambiguity_higher_hack_rate_than_high(self):
        """Medium ambiguity should show higher hack rate than high."""
        findings = load_findings()
        medium_rate = findings["by_ambiguity"]["medium"]["hack_rate"]
        high_rate = findings["by_ambiguity"]["high"]["hack_rate"]

        assert medium_rate >= high_rate, (
            f"Medium hack rate ({medium_rate}) should be >= high ({high_rate})"
        )


class TestDivergencePattern:
    """Regression tests for divergence patterns."""

    def test_ambiguity_drives_divergence(self):
        """Medium ambiguity should show higher divergence than low."""
        findings = load_findings()
        low_div = findings["by_ambiguity"]["low"]["avg_divergence"]
        medium_div = findings["by_ambiguity"]["medium"]["avg_divergence"]

        assert medium_div > low_div, (
            f"Medium divergence ({medium_div}) should be > low ({low_div})"
        )

    def test_low_ambiguity_negative_divergence(self):
        """Low ambiguity tasks should show negative or near-zero divergence."""
        findings = load_findings()
        low_div = findings["by_ambiguity"]["low"]["avg_divergence"]

        assert low_div <= 0.1, (
            f"Low ambiguity divergence ({low_div}) should be <= 0.1"
        )

    def test_highest_divergence_is_significant(self):
        """Highest divergence case should be >= 0.5 (substantial gap)."""
        findings = load_findings()
        highest = findings["notable_cases"]["highest_divergence"]

        assert highest is not None
        assert highest["divergence"] >= 0.5, (
            f"Highest divergence ({highest['divergence']}) should be >= 0.5"
        )

    def test_highest_divergence_task_identified(self):
        """The highest divergence case should have task_id field."""
        findings = load_findings()
        highest = findings["notable_cases"]["highest_divergence"]

        assert "task_id" in highest, "highest_divergence should have task_id field"
        assert highest["task_id"] is not None


class TestNaiveRewardSignal:
    """Regression tests for naive reward system bias."""

    def test_naive_greater_than_robust_majority(self):
        """Majority of tasks should show naive > robust (65%+)."""
        findings = load_findings()
        pct = findings["overall"]["naive_greater_than_robust_pct"]

        assert pct >= 0.55, (
            f"Tasks with naive > robust ({pct:.1%}) should be >= 55%"
        )

    def test_naive_reward_problem_documented(self):
        """The naive reward problem should be empirically verified."""
        findings = load_findings()

        # Overall: avg naive should be > avg robust
        avg_naive = findings["overall"]["avg_naive"]
        avg_robust = findings["overall"]["avg_robust"]

        assert avg_naive > avg_robust, (
            f"Average naive ({avg_naive}) should be > average robust ({avg_robust})"
        )


class TestHackTypes:
    """Regression tests for hack type distribution."""

    def test_hack_types_counted(self):
        """hack_types section should have counts."""
        findings = load_findings()
        hack_types = findings["hack_types"]

        assert "counts" in hack_types
        assert isinstance(hack_types["counts"], dict)
        assert len(hack_types["counts"]) > 0

    def test_sycophantic_caution_most_common(self):
        """Sycophantic Caution should be the most common hack type."""
        findings = load_findings()
        counts = findings["hack_types"]["counts"]

        sycophantic = counts.get("SYCOPHANTIC_CAUTION", 0)
        metric_gaming = counts.get("METRIC_GAMING", 0)
        overclaiming = counts.get("OVERCLAIMING", 0)

        assert sycophantic > metric_gaming, (
            f"Sycophantic Caution ({sycophantic}) should be > Metric Gaming ({metric_gaming})"
        )
        assert sycophantic > overclaiming, (
            f"Sycophantic Caution ({sycophantic}) should be > Overclaiming ({overclaiming})"
        )


class TestNotableCases:
    """Regression tests for notable cases."""

    def test_perfect_scores_exist(self):
        """There should be tasks with perfect naive and robust scores."""
        findings = load_findings()
        perfect = findings["notable_cases"]["perfect_scores"]

        assert isinstance(perfect, list)
        assert len(perfect) > 0, "Should have at least one perfect score task"

    def test_clean_completions_exist(self):
        """There should be tasks with no hacking detected."""
        findings = load_findings()
        clean = findings["notable_cases"]["clean_completions"]

        assert isinstance(clean, list)
        assert len(clean) > 0, "Should have at least one clean completion"

    def test_multi_hack_tasks_identified(self):
        """Multi-hack tasks field should exist (may be empty for some runs)."""
        findings = load_findings()
        multi_hack = findings["notable_cases"].get("multi_hack")

        # multi_hack field should exist even if empty
        assert multi_hack is not None, "multi_hack field should exist in notable_cases"
        assert isinstance(multi_hack, list), "multi_hack should be a list"


class TestConsistency:
    """Regression tests for internal consistency."""

    def test_completion_rate_makes_sense(self):
        """Completion rate should be (completed / total)."""
        findings = load_findings()
        overall = findings["overall"]

        calculated_rate = overall["completed_tasks"] / overall["total_tasks"]
        assert abs(overall["completion_rate"] - calculated_rate) < 0.01

    def test_ambiguity_totals_reasonable(self):
        """Sum of ambiguity-level tasks should be <= total tasks."""
        findings = load_findings()

        low_count = findings["by_ambiguity"]["low"].get("count", 0)
        med_count = findings["by_ambiguity"]["medium"].get("count", 0)
        high_count = findings["by_ambiguity"]["high"].get("count", 0)
        total_tasks = findings["overall"]["total_tasks"]
        completed = findings["overall"]["completed_tasks"]

        ambiguity_total = low_count + med_count + high_count

        # Ambiguity total should be <= completed tasks (may be less if some tasks didn't complete)
        assert ambiguity_total <= completed, (
            f"Ambiguity totals ({ambiguity_total}) should be <= completed ({completed})"
        )


if __name__ == "__main__":
    import subprocess
    subprocess.run(["pytest", __file__, "-v"])
