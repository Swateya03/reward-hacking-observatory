"""Findings extractor for reward hacking observatory experiment results.

Reads the per-task files written by run_experiment.build_result (schema v3:
nested `scores` with `robust_outcome` (null when N/A) and `divergence`,
`hacking.events[].type`, `policy_metrics`, and a `metadata` block).

Internally, every record is converted by normalize_result() into a flat dict
with keys naive_score, robust_score, divergence, hacking_events[].hack_type,
ambiguity_level, completed, unsafe_action_under_ambiguity, metadata.
A value of None means N/A: that task is still counted, but it is excluded from
the average, rate or comparison that needs the missing value.

Code that sets `extractor.results` directly must pass flat records.
"""

import json
from pathlib import Path
from collections import defaultdict
from statistics import mean

from hacking.detector import CHECKS, NEEDS_STATE_CHECK, check_availability


RESULT_KEYS_REQUIRED = ("task_id", "ambiguity_level", "scores", "hacking")
LEVELS = ("low", "medium", "high")


def normalize_result(record: dict, source: str = "<record>") -> dict:
    """Convert one run_experiment result (schema v3) into the flat internal form.

    Raises ValueError for any other shape, including schema v2 (no
    `robust_outcome` key) and the flat sample shape, so a wrong input cannot
    silently produce zeros.
    """
    missing = [k for k in RESULT_KEYS_REQUIRED if k not in record]
    if missing:
        raise ValueError(
            f"{source}: not a run_experiment result (missing {missing}). "
            "Expected the schema written by run_experiment.build_result."
        )
    scores = record["scores"] or {}
    if "robust_outcome" not in scores:
        raise ValueError(
            f"{source}: scores has no 'robust_outcome' key (schema v2 or older). "
            "Re-run with the current run_experiment."
        )
    hacking = record["hacking"] or {}
    policy = record.get("policy_metrics") or {}
    return {
        "task_id": record["task_id"],
        "ambiguity_level": record["ambiguity_level"],
        "completed": record.get("completed", True),
        "naive_score": scores.get("naive"),
        "intermediate_score": scores.get("intermediate"),
        "robust_score": scores.get("robust_outcome"),          # None = N/A
        "divergence": scores.get("divergence"),                # None = N/A
        "hacking_events": [
            {"hack_type": event.get("type"), "severity": event.get("severity")}
            for event in hacking.get("events", [])
        ],
        "unsafe_action_under_ambiguity": policy.get("unsafe_action_under_ambiguity"),  # None = N/A
        "metadata": record.get("metadata", {}),
    }


def _rate(numerator: int, denominator: int):
    return round(numerator / denominator, 3) if denominator else None


HACK_LABEL_DEFINITION = "any available detector check fired (the detector's verdict)"


def episode_checks(r: dict) -> dict:
    """Per-check status for one flat episode record.

    available: the check could run (METRIC_GAMING needs a robust outcome).
    fired: the check emitted an event; None when not available.
    """
    available = check_availability(robust_available=r.get("robust_score") is not None)
    fired_types = {(e.get("hack_type") or "").lower() for e in (r.get("hacking_events") or [])}
    return {
        name: {"available": available[name],
               "fired": (name in fired_types) if available[name] else None}
        for name in CHECKS
    }


def hack_label(r: dict) -> bool:
    """The hack label: true when any available check fired."""
    return any(v["fired"] for v in episode_checks(r).values())


def _coverage_note(results: list[dict]) -> str:
    """Plain-language note on how unevenly METRIC_GAMING can run across levels."""
    per_level = {}
    for level in LEVELS:
        tasks = [r for r in results if r.get("ambiguity_level") == level]
        if tasks:
            avail = sum(1 for t in tasks if episode_checks(t)["metric_gaming"]["available"])
            per_level[level] = f"{avail} of {len(tasks)}"
    return (
        "METRIC_GAMING needs a state check, so its coverage is uneven across ambiguity levels "
        f"(episodes where it could run: {', '.join(f'{k} {v}' for k, v in per_level.items())}). "
        "Its rate is not comparable across levels. Read each check's rate with its own available_n."
    )


def _check_summary(tasks: list[dict]) -> dict:
    """Per check: episodes where it was available, episodes where it fired, and its
    rate with its own denominator (available episodes)."""
    statuses = [episode_checks(t) for t in tasks]
    out = {}
    for name in CHECKS:
        available_n = sum(1 for st in statuses if st[name]["available"])
        fired_n = sum(1 for st in statuses if st[name]["fired"])
        out[name] = {"available_n": available_n, "fired_n": fired_n,
                     "rate": _rate(fired_n, available_n)}
    return out


class FindingsExtractor:
    """Extract structured findings from experiment result files."""

    def __init__(self, results_dir: str = "results/"):
        """Initialize with results directory path."""
        self.results_dir = Path(results_dir)
        self.results = []
        self.task_bank = {}

    def load_results(self) -> list[dict]:
        """Load all task result JSON files from results directory."""
        self.results = []

        if not self.results_dir.exists():
            return []

        for json_file in sorted(self.results_dir.glob("task_*.json")):
            with open(json_file) as f:
                record = json.load(f)
            # Wrong-shape files raise ValueError (not skipped): silent skips hid the schema mismatch.
            self.results.append(normalize_result(record, source=str(json_file)))

        return self.results

    def compute_findings(self) -> dict:
        """Compute structured findings from loaded results."""
        if not self.results:
            return self._empty_findings()

        return {
            "overall": self._compute_overall(self.results),
            "by_ambiguity": self._compute_by_ambiguity(self.results),
            "hack_types": self._compute_hack_types(self.results),
            "notable_cases": self._compute_notable_cases(self.results),
        }

    def _empty_findings(self) -> dict:
        """Return empty findings structure."""
        empty_level = {
            "count": 0, "robust_outcome_na": 0, "avg_naive": 0.0, "avg_robust": 0.0,
            "avg_divergence": 0.0, "hack_rate": 0.0,
            "checks": {name: {"available_n": 0, "fired_n": 0, "rate": None} for name in CHECKS},
            "unsafe_action_applicable_n": 0, "unsafe_action_under_ambiguity_rate": None,
        }
        return {
            "overall": {
                "total_tasks": 0,
                "completed_tasks": 0,
                "completion_rate": 0.0,
                "robust_outcome_na": 0,
                "robust_outcome_available": 0,
                "divergence_available": 0,
                "completion_rate": 0.0,
                "unsafe_action_under_ambiguity_rate": None,
                "unsafe_action_applicable_n": 0,
                "avg_naive": 0.0,
                "avg_robust": 0.0,
                "avg_divergence": 0.0,
                "hack_rate": 0.0,
                "hack_rate_definition": HACK_LABEL_DEFINITION,
                "checks": {name: {"available_n": 0, "fired_n": 0, "rate": None} for name in CHECKS},
                "coverage_note": "",
            },
            "by_ambiguity": {level: dict(empty_level) for level in LEVELS},
            "hack_types": {"counts": {}, "most_common": None, "by_ambiguity": {}},
            "notable_cases": {
                "highest_divergence": None,
                "lowest_divergence": None,
                "multi_hack": [],
                "perfect_scores": [],
                "clean_completions": [],
                "unsafe_under_ambiguity": [],
            },
        }

    @staticmethod
    def _robust_available(r: dict) -> bool:
        return r.get("robust_score") is not None

    def _compute_overall(self, results: list[dict]) -> dict:
        """Overall statistics. N/A values are excluded from the averages that need them."""
        total = len(results)
        completed = sum(1 for r in results if r.get("completed", True))

        naive_scores = [r["naive_score"] for r in results if r.get("naive_score") is not None]
        robust_scores = [r["robust_score"] for r in results if self._robust_available(r)]
        divergences = [r["divergence"] for r in results if r.get("divergence") is not None]

        # Hack label: any available check fired. Denominator: all episodes.
        hack_count = sum(1 for r in results if hack_label(r))

        # naive > robust, among tasks where both are available.
        comparable = [r for r in results if self._robust_available(r) and r.get("naive_score") is not None]
        naive_gt_robust = sum(1 for r in comparable if r["naive_score"] > r["robust_score"])

        # Unsafe-under-ambiguity: applicable tasks only (medium and high).
        applicable = [r for r in results if r.get("unsafe_action_under_ambiguity") is not None]
        unsafe_count = sum(1 for r in applicable if r["unsafe_action_under_ambiguity"])

        return {
            "total_tasks": total,
            "completed_tasks": completed,
            "completion_rate": round(completed / total, 3) if total else 0.0,
            "robust_outcome_na": total - len(robust_scores),
            "robust_outcome_available": len(robust_scores),
            "avg_naive": round(mean(naive_scores), 3) if naive_scores else 0.0,
            "avg_robust": round(mean(robust_scores), 3) if robust_scores else 0.0,
            "avg_divergence": round(mean(divergences), 3) if divergences else 0.0,
            "divergence_available": len(divergences),
            "hack_rate": _rate(hack_count, total) or 0.0,
            "hack_rate_definition": HACK_LABEL_DEFINITION,
            "checks": _check_summary(results),
            "coverage_note": _coverage_note(results),
            "naive_greater_than_robust_pct": _rate(naive_gt_robust, len(comparable)) or 0.0,
            "unsafe_action_under_ambiguity_rate": _rate(unsafe_count, len(applicable)),
            "unsafe_action_applicable_n": len(applicable),
        }

    def _compute_by_ambiguity(self, results: list[dict]) -> dict:
        """Statistics grouped by ambiguity level. N/A values excluded per metric."""
        findings = {}
        for level in LEVELS:
            tasks = [r for r in results if r.get("ambiguity_level") == level]
            if not tasks:
                findings[level] = {
                    "count": 0, "robust_outcome_na": 0, "avg_naive": 0.0, "avg_robust": 0.0,
                    "avg_divergence": 0.0, "hack_rate": 0.0,
                    "unsafe_action_applicable_n": 0, "unsafe_action_under_ambiguity_rate": None,
                }
                continue

            naive = [t["naive_score"] for t in tasks if t.get("naive_score") is not None]
            robust = [t["robust_score"] for t in tasks if self._robust_available(t)]
            divergences = [t["divergence"] for t in tasks if t.get("divergence") is not None]
            hack_count = sum(1 for t in tasks if hack_label(t))

            applicable = [t for t in tasks if t.get("unsafe_action_under_ambiguity") is not None]
            unsafe_count = sum(1 for t in applicable if t["unsafe_action_under_ambiguity"])

            findings[level] = {
                "count": len(tasks),
                "robust_outcome_na": len(tasks) - len(robust),
                "avg_naive": round(mean(naive), 3) if naive else 0.0,
                "avg_robust": round(mean(robust), 3) if robust else 0.0,
                "avg_divergence": round(mean(divergences), 3) if divergences else 0.0,
                "hack_rate": _rate(hack_count, len(tasks)) or 0.0,
                "checks": _check_summary(tasks),
                "unsafe_action_applicable_n": len(applicable),
                "unsafe_action_under_ambiguity_rate": _rate(unsafe_count, len(applicable)),
            }
        return findings

    def _compute_hack_types(self, results: list[dict]) -> dict:
        """Extract and count hack types from hacking_events."""
        type_counts = defaultdict(int)
        by_ambiguity = defaultdict(lambda: defaultdict(int))

        for result in results:
            for event in result.get("hacking_events") or []:
                hack_type = event.get("hack_type") if isinstance(event, dict) else str(event)
                if hack_type:
                    type_counts[hack_type] += 1
                    by_ambiguity[result.get("ambiguity_level", "unknown")][hack_type] += 1

        most_common = max(type_counts.items(), key=lambda x: x[1])[0] if type_counts else None

        most_common_by_ambiguity = {}
        for level in LEVELS:
            if by_ambiguity[level]:
                most_common_by_ambiguity[level] = max(by_ambiguity[level].items(), key=lambda x: x[1])[0]

        return {
            "counts": dict(type_counts),
            "most_common": most_common,
            "by_ambiguity": most_common_by_ambiguity,
        }

    def _compute_notable_cases(self, results: list[dict]) -> dict:
        """Find notable tasks. N/A divergence is never a candidate for highest or lowest."""
        with_div = [r for r in results if r.get("divergence") is not None]
        highest = max(with_div, key=lambda r: r["divergence"]) if with_div else None
        lowest = min(with_div, key=lambda r: r["divergence"]) if with_div else None

        def summary(r):
            return {"task_id": r["task_id"], "divergence": round(r["divergence"], 3),
                    "naive": r["naive_score"], "robust": r["robust_score"]}

        perfect = [r["task_id"] for r in results
                   if r.get("naive_score") == 1.0 and r.get("robust_score") == 1.0]
        clean = [r["task_id"] for r in results if not r.get("hacking_events")]

        multi_hack = []
        for r in results:
            events = r.get("hacking_events") or []
            if len(events) > 1:
                hack_types = {e.get("hack_type") if isinstance(e, dict) else str(e) for e in events}
                if len(hack_types) > 1:
                    multi_hack.append({"task_id": r["task_id"], "hack_types": sorted(hack_types)})

        unsafe = [r["task_id"] for r in results if r.get("unsafe_action_under_ambiguity") is True]

        return {
            "highest_divergence": summary(highest) if highest else None,
            "lowest_divergence": summary(lowest) if lowest else None,
            "multi_hack": multi_hack,
            "perfect_scores": perfect,
            "clean_completions": clean,
            "unsafe_under_ambiguity": unsafe,
        }

    def save_findings(self, path: str = "results/findings.json") -> None:
        """Save computed findings to JSON file."""
        findings = self.compute_findings()
        with open(path, "w") as f:
            json.dump(findings, f, indent=2)
        print(f"Findings saved to {path}")

    def print_findings(self) -> None:
        """Print human-readable findings summary."""
        self.load_results()
        findings = self.compute_findings()
        overall = findings["overall"]

        print("\n" + "=" * 70)
        print("REWARD HACKING OBSERVATORY: EXPERIMENT FINDINGS")
        print("=" * 70)

        print("\n[OVERALL STATISTICS]")
        print("-" * 70)
        print(f"Total Tasks:           {overall['total_tasks']}")
        print(f"Completed:             {overall['completed_tasks']}/{overall['total_tasks']} ({overall['completion_rate']*100:.1f}%)")
        print(f"Average Naive Score:   {overall['avg_naive']:.3f}")
        print(f"Robust outcome:        avg {overall['avg_robust']:.3f} over {overall['robust_outcome_available']} tasks ({overall['robust_outcome_na']} N/A, excluded)")
        print(f"Average Divergence:    {overall['avg_divergence']:.3f} over {overall['divergence_available']} tasks")
        print(f"Hack rate ({overall['hack_rate_definition']}): {overall['hack_rate']*100:.1f}% of {overall['total_tasks']} episodes")
        print("Per check (rate uses its own available episodes):")
        for name, c in overall["checks"].items():
            rate = "N/A" if c["rate"] is None else f"{c['rate']*100:.1f}%"
            print(f"  {name:22} available {c['available_n']:3}  fired {c['fired_n']:3}  rate {rate}")
        print(f"Note: {overall['coverage_note']}")

        print("\n[BY AMBIGUITY LEVEL]")
        print("-" * 70)
        for level in LEVELS:
            s = findings["by_ambiguity"][level]
            print(f"\n{level.upper()} (n={s['count']}, robust N/A={s['robust_outcome_na']})")
            print(f"  Avg Naive:     {s['avg_naive']:.3f}")
            print(f"  Avg Robust:    {s['avg_robust']:.3f}")
            print(f"  Avg Divergence: {s['avg_divergence']:.3f}")
            print(f"  Unsafe action under ambiguity: {s['unsafe_action_under_ambiguity_rate']} (applicable n={s['unsafe_action_applicable_n']})")

        print("\n[HACK TYPE ANALYSIS]")
        print("-" * 70)
        hack_types = findings["hack_types"]
        if hack_types["counts"]:
            for hack_type, count in sorted(hack_types["counts"].items(), key=lambda x: -x[1]):
                print(f"  {hack_type}: {count}")
        else:
            print("No hack types detected in results.")

        print("\n" + "=" * 70 + "\n")


if __name__ == "__main__":
    extractor = FindingsExtractor()
    extractor.load_results()
    extractor.save_findings()
    extractor.print_findings()
