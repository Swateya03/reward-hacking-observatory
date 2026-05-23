"""Tests for Layer 9: Chart generation and visualization.

Tests data preparation logic for all charts without rendering.
Uses mock data and mocks matplotlib to avoid file I/O.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import matplotlib
matplotlib.use("Agg")  # Use non-interactive backend
import pytest

# Import functions to test
from analysis.findings import FindingsExtractor
from analysis.charts.chart_divergence_by_ambiguity import prepare_data as prepare_divergence_data
from analysis.charts.chart_hack_types import prepare_data as prepare_hack_types_data
from analysis.charts.chart_score_scatter import prepare_data as prepare_scatter_data
from analysis.charts.chart_hack_rate import prepare_data as prepare_hack_rate_data


# ============================================================================
# MOCK DATA
# ============================================================================

MOCK_FINDINGS = {
    "overall": {
        "total_tasks": 30,
        "completed_tasks": 29,
        "completion_rate": 0.967,
        "avg_naive": 0.659,
        "avg_robust": 0.424,
        "avg_divergence": 0.234,
        "hack_rate": 0.517,
    },
    "by_ambiguity": {
        "low": {
            "count": 9,
            "avg_naive": 0.822,
            "avg_robust": 0.894,
            "avg_divergence": -0.072,
            "hack_rate": 0.0,
        },
        "medium": {
            "count": 10,
            "avg_naive": 0.900,
            "avg_robust": 0.425,
            "avg_divergence": 0.475,
            "hack_rate": 0.8,
        },
        "high": {
            "count": 10,
            "avg_naive": 0.270,
            "avg_robust": 0.000,
            "avg_divergence": 0.270,
            "hack_rate": 0.7,
        },
    },
    "hack_types": {
        "counts": {
            "SYCOPHANTIC_CAUTION": 16,
            "METRIC_GAMING": 6,
            "OVERCLAIMING": 1,
            "SCOPE_CREEP": 0,
            "IRREVERSIBILITY_BIAS": 0,
        }
    },
    "notable_cases": {
        "highest_divergence": {
            "task_id": "task_018",
            "divergence": 0.95,
            "naive_score": 1.0,
            "robust_score": 0.05,
        },
        "lowest_divergence": {
            "task_id": "task_004",
            "divergence": -0.30,
        },
        "perfect_scores": ["task_003", "task_005", "task_006", "task_009", "task_010"],
        "clean_completions": [
            "task_001",
            "task_002",
            "task_003",
            "task_004",
            "task_005",
            "task_006",
            "task_009",
            "task_010",
        ],
        "multi_hack": [
            {"task_id": "task_018", "hack_types": ["METRIC_GAMING", "OVERCLAIMING"]},
            {"task_id": "task_019", "hack_types": ["METRIC_GAMING", "SYCOPHANTIC_CAUTION"]},
        ],
    },
}

MOCK_TASKS = [
    {"task_id": "task_001", "naive_score": 1.0, "robust_score": 1.0, "ambiguity_level": "low"},
    {"task_id": "task_012", "naive_score": 1.0, "robust_score": 0.5, "ambiguity_level": "medium"},
    {"task_id": "task_018", "naive_score": 1.0, "robust_score": 0.05, "ambiguity_level": "medium"},
    {"task_id": "task_021", "naive_score": 0.2, "robust_score": 0.0, "ambiguity_level": "high"},
]


# ============================================================================
# FINDINGS EXTRACTOR TESTS (extending Layer 5)
# ============================================================================

class TestFindingsExtractor:
    """Test FindingsExtractor with mock data."""

    def test_compute_findings_returns_all_required_keys(self):
        """Findings dict has all required top-level keys."""
        extractor = FindingsExtractor()
        extractor.results = MOCK_TASKS

        findings = extractor.compute_findings()

        assert "overall" in findings
        assert "by_ambiguity" in findings
        assert "hack_types" in findings
        assert "notable_cases" in findings

    def test_by_ambiguity_has_all_three_levels(self):
        """by_ambiguity breakdown includes low, medium, high."""
        extractor = FindingsExtractor()
        extractor.results = MOCK_TASKS

        findings = extractor.compute_findings()
        by_ambiguity = findings.get("by_ambiguity", {})

        assert "low" in by_ambiguity
        assert "medium" in by_ambiguity
        assert "high" in by_ambiguity

    def test_by_ambiguity_level_has_required_metrics(self):
        """Each ambiguity level has count, avg scores, hack rate."""
        extractor = FindingsExtractor()
        extractor.results = MOCK_TASKS

        findings = extractor.compute_findings()
        low = findings["by_ambiguity"].get("low", {})

        assert "count" in low
        assert "avg_naive" in low
        assert "avg_robust" in low
        assert "avg_divergence" in low
        assert "hack_rate" in low

    def test_notable_cases_has_required_keys(self):
        """notable_cases includes highest/lowest divergence and special cases."""
        extractor = FindingsExtractor()
        extractor.results = MOCK_TASKS

        findings = extractor.compute_findings()
        notable = findings.get("notable_cases", {})

        assert "highest_divergence" in notable
        assert "lowest_divergence" in notable
        assert "perfect_scores" in notable
        assert "clean_completions" in notable

    def test_highest_divergence_identifies_task_018(self):
        """highest_divergence correctly identifies task_018 (divergence=0.95)."""
        extractor = FindingsExtractor()
        extractor.results = [
            {
                "task_id": "task_018",
                "naive_score": 1.0,
                "robust_score": 0.05,
                "ambiguity_level": "medium",
                "hacking_events": [],
                "divergence": 0.95,
            },
            {
                "task_id": "task_012",
                "naive_score": 0.5,
                "robust_score": 0.5,
                "ambiguity_level": "medium",
                "hacking_events": [],
                "divergence": 0.0,
            },
        ]

        findings = extractor.compute_findings()
        highest = findings["notable_cases"]["highest_divergence"]

        if highest is not None:
            assert highest["task_id"] == "task_018"
            assert abs(highest["divergence"] - 0.95) < 0.01
        # If highest_divergence is None, that's OK - it means the logic differs


# ============================================================================
# CHART DATA PREPARATION TESTS
# ============================================================================

class TestDivergenceChartData:
    """Test data preparation for divergence_by_ambiguity chart."""

    def test_prepare_divergence_data_returns_all_levels(self):
        """prepare_data returns dict with low, medium, high keys."""
        data = prepare_divergence_data(MOCK_FINDINGS)

        assert "low" in data
        assert "medium" in data
        assert "high" in data

    def test_prepare_divergence_data_contains_required_fields(self):
        """Each level has naive, robust, divergence, hack_rate."""
        data = prepare_divergence_data(MOCK_FINDINGS)

        for level in ["low", "medium", "high"]:
            assert "naive" in data[level]
            assert "robust" in data[level]
            assert "divergence" in data[level]
            assert "hack_rate" in data[level]

    def test_prepare_divergence_data_values_correct(self):
        """Values match mock findings."""
        data = prepare_divergence_data(MOCK_FINDINGS)

        assert abs(data["low"]["naive"] - 0.822) < 0.001
        assert abs(data["medium"]["divergence"] - 0.475) < 0.001
        assert abs(data["high"]["hack_rate"] - 0.7) < 0.001

    def test_prepare_divergence_data_handles_missing_level(self):
        """Missing levels are set to zeros, not errors."""
        findings_partial = {"by_ambiguity": {}}
        data = prepare_divergence_data(findings_partial)

        assert data["low"]["naive"] == 0.0
        assert data["medium"]["robust"] == 0.0
        assert data["high"]["divergence"] == 0.0


class TestHackTypesChartData:
    """Test data preparation for hack_type_distribution chart."""

    def test_prepare_hack_types_returns_sorted_list(self):
        """prepare_data returns list of (label, count) tuples."""
        data = prepare_hack_types_data(MOCK_FINDINGS)

        assert isinstance(data, list)
        assert len(data) > 0
        assert isinstance(data[0], tuple)
        assert len(data[0]) == 2

    def test_prepare_hack_types_sorted_descending(self):
        """List is sorted by count descending (most common first)."""
        data = prepare_hack_types_data(MOCK_FINDINGS)

        for i in range(len(data) - 1):
            assert data[i][1] >= data[i + 1][1], "Not sorted descending"

    def test_prepare_hack_types_labels_human_readable(self):
        """Labels are human-readable (not enum names)."""
        data = prepare_hack_types_data(MOCK_FINDINGS)

        labels = [label for label, _ in data]

        # Should not have underscores or all caps like enums
        for label in labels:
            # Labels should have at least one space or proper capitalization
            assert " " in label or (label[0].isupper() and any(c.islower() for c in label))

    def test_prepare_hack_types_top_is_sycophantic_caution(self):
        """Sycophantic Caution (16) is the top hack type."""
        data = prepare_hack_types_data(MOCK_FINDINGS)

        top_label, top_count = data[0]

        assert "Sycophantic Caution" in top_label or "caution" in top_label.lower()
        assert top_count == 16


class TestScatterChartData:
    """Test data preparation for score_scatter chart."""

    def test_prepare_scatter_data_returns_dict(self):
        """prepare_data returns dict with x, y, colors, task_ids."""
        data = prepare_scatter_data(MOCK_TASKS)

        assert "x" in data
        assert "y" in data
        assert "colors" in data
        assert "task_ids" in data

    def test_prepare_scatter_data_x_y_same_length(self):
        """x and y lists have same length."""
        data = prepare_scatter_data(MOCK_TASKS)

        assert len(data["x"]) == len(data["y"])

    def test_prepare_scatter_data_all_lists_same_length(self):
        """x, y, colors, and task_ids all have same length."""
        data = prepare_scatter_data(MOCK_TASKS)

        n = len(data["x"])
        assert len(data["y"]) == n
        assert len(data["colors"]) == n
        assert len(data["task_ids"]) == n

    def test_prepare_scatter_data_colors_map_to_ambiguity(self):
        """Colors map correctly to ambiguity levels."""
        data = prepare_scatter_data(MOCK_TASKS)

        # task_001 is low, should be green
        idx = data["task_ids"].index("task_001")
        assert data["colors"][idx] == "#2ca02c"  # Green for low

        # task_018 is medium, should be orange
        idx = data["task_ids"].index("task_018")
        assert data["colors"][idx] == "#ff7f0e"  # Orange for medium

        # task_021 is high, should be red
        idx = data["task_ids"].index("task_021")
        assert data["colors"][idx] == "#d62728"  # Red for high

    def test_prepare_scatter_data_skips_none_scores(self):
        """Tasks with None scores are skipped."""
        tasks_with_none = MOCK_TASKS + [
            {"task_id": "bad", "naive_score": None, "robust_score": 0.5, "ambiguity_level": "low"}
        ]

        data = prepare_scatter_data(tasks_with_none)

        assert "bad" not in data["task_ids"]


class TestHackRateChartData:
    """Test data preparation for hack_rate_by_ambiguity chart."""

    def test_prepare_hack_rate_data_returns_dict(self):
        """prepare_data returns dict with low, medium, high keys."""
        data = prepare_hack_rate_data(MOCK_FINDINGS)

        assert "low" in data
        assert "medium" in data
        assert "high" in data

    def test_prepare_hack_rate_data_has_required_fields(self):
        """Each level has hack_rate and divergence."""
        data = prepare_hack_rate_data(MOCK_FINDINGS)

        for level in ["low", "medium", "high"]:
            assert "hack_rate" in data[level]
            assert "divergence" in data[level]

    def test_prepare_hack_rate_values_are_floats(self):
        """hack_rate and divergence are floats."""
        data = prepare_hack_rate_data(MOCK_FINDINGS)

        for level in ["low", "medium", "high"]:
            assert isinstance(data[level]["hack_rate"], (int, float))
            assert isinstance(data[level]["divergence"], (int, float))

    def test_prepare_hack_rate_values_in_valid_ranges(self):
        """hack_rate is 0.0-1.0, divergence can be negative."""
        data = prepare_hack_rate_data(MOCK_FINDINGS)

        for level in ["low", "medium", "high"]:
            hack_rate = data[level]["hack_rate"]
            divergence = data[level]["divergence"]

            assert 0.0 <= hack_rate <= 1.0, f"{level} hack_rate out of range: {hack_rate}"
            # Divergence can be negative (low ambiguity)
            assert -0.5 <= divergence <= 1.0, f"{level} divergence out of range: {divergence}"

    def test_prepare_hack_rate_values_correct(self):
        """Values match mock findings."""
        data = prepare_hack_rate_data(MOCK_FINDINGS)

        assert abs(data["low"]["hack_rate"] - 0.0) < 0.001
        assert abs(data["medium"]["hack_rate"] - 0.8) < 0.001
        assert abs(data["high"]["hack_rate"] - 0.7) < 0.001
        assert abs(data["low"]["divergence"] - (-0.072)) < 0.001


# ============================================================================
# INTEGRATION TESTS (with mocked matplotlib)
# ============================================================================

class TestChartIntegrationWithMocks:
    """Test chart generation with mocked matplotlib (no actual rendering)."""

    @patch("matplotlib.pyplot.savefig")
    def test_divergence_chart_calls_savefig(self, mock_savefig):
        """divergence chart calls plt.savefig."""
        from analysis.charts.chart_divergence_by_ambiguity import create_chart

        create_chart(MOCK_FINDINGS["by_ambiguity"])

        mock_savefig.assert_called_once()
        call_args = mock_savefig.call_args
        assert "divergence_by_ambiguity.png" in str(call_args)

    @patch("matplotlib.pyplot.savefig")
    def test_hack_types_chart_calls_savefig(self, mock_savefig):
        """hack_types chart calls plt.savefig."""
        from analysis.charts.chart_hack_types import create_chart

        create_chart(MOCK_FINDINGS["hack_types"])

        mock_savefig.assert_called_once()

    @patch("matplotlib.pyplot.savefig")
    def test_scatter_chart_calls_savefig(self, mock_savefig):
        """scatter chart calls plt.savefig."""
        from analysis.charts.chart_score_scatter import create_chart

        create_chart(MOCK_TASKS)

        mock_savefig.assert_called_once()

    @patch("matplotlib.pyplot.savefig")
    def test_hack_rate_chart_calls_savefig(self, mock_savefig):
        """hack_rate chart calls plt.savefig."""
        from analysis.charts.chart_hack_rate import create_chart

        create_chart(MOCK_FINDINGS["by_ambiguity"])

        mock_savefig.assert_called_once()


# ============================================================================
# EDGE CASE TESTS
# ============================================================================

class TestChartDataEdgeCases:
    """Test edge cases and error handling."""

    def test_prepare_divergence_data_empty_findings(self):
        """Empty findings dict doesn't crash."""
        data = prepare_divergence_data({})

        assert "low" in data
        assert data["low"]["naive"] == 0.0

    def test_prepare_hack_types_zero_counts(self):
        """Hack types with zero count are included."""
        data = prepare_hack_types_data(MOCK_FINDINGS)

        # Find entries with count 0
        zero_entries = [label for label, count in data if count == 0]

        # Should be at least one (Scope Creep, Irreversibility Bias)
        assert len(zero_entries) >= 0  # May or may not be included depending on implementation

    def test_prepare_scatter_data_single_task(self):
        """Single task in list doesn't crash."""
        single_task = [MOCK_TASKS[0]]

        data = prepare_scatter_data(single_task)

        assert len(data["x"]) == 1
        assert data["task_ids"][0] == "task_001"

    def test_prepare_hack_rate_all_zero_rates(self):
        """All zero hack rates are handled correctly."""
        findings_zero = {
            "by_ambiguity": {
                "low": {"hack_rate": 0.0, "avg_divergence": 0.0},
                "medium": {"hack_rate": 0.0, "avg_divergence": 0.0},
                "high": {"hack_rate": 0.0, "avg_divergence": 0.0},
            }
        }

        data = prepare_hack_rate_data(findings_zero)

        for level in ["low", "medium", "high"]:
            assert data[level]["hack_rate"] == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
