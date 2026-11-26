"""
Cost tracking and the hard budget guard.

- cost_of_usage(): turns the usage fields of one API response into USD, using
  the prices in config.PRICING (source and date are recorded there).
- CostTracker: appends one line per API call to
  results/runs/<model>/cost_log.jsonl and keeps the running total. The total is
  read back from that file on start, so a resumed run continues the same count.
- Before each call, guard() adds the worst-case cost of that call to the running
  total. If the sum would exceed config.BUDGET_USD, it raises BudgetExceeded and
  the call is not made.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import config


class BudgetExceeded(RuntimeError):
    """Raised before a call that would take a total over its cap.
    scope is "overall" (config.BUDGET_USD) or "run" (config.RUN_BUDGET_USD)."""

    def __init__(self, running_total: float, worst_case: float, budget: float,
                 task_id: str | None = None, step: int | None = None,
                 scope: str = "overall", run_id: str | None = None):
        self.running_total = running_total
        self.worst_case = worst_case
        self.budget = budget
        self.task_id = task_id
        self.step = step
        self.scope = scope
        self.run_id = run_id
        super().__init__(
            f"budget guard ({scope}): running total ${running_total:.6f} + worst case ${worst_case:.6f} "
            f"would exceed ${budget:.2f}"
        )


def default_log_path(model: str) -> Path:
    return Path("results") / "runs" / model / "cost_log.jsonl"


def _tier(model: str, prompt_tokens: int) -> dict:
    tiers = config.PRICING[model]["tiers"]
    for tier in tiers:
        if tier["max_prompt_tokens"] is None or prompt_tokens <= tier["max_prompt_tokens"]:
            return tier
    return tiers[-1]


def cost_of_usage(model: str, usage: dict) -> float:
    """USD for one response. usage keys: input_tokens, output_tokens,
    cache_creation_input_tokens, cache_read_input_tokens (missing or None counts as 0)."""
    inp = usage.get("input_tokens") or 0
    out = usage.get("output_tokens") or 0
    cw = usage.get("cache_creation_input_tokens") or 0
    cr = usage.get("cache_read_input_tokens") or 0
    prompt_tokens = inp + cw + cr  # the page's tier rule counts cache reads and writes too
    t = _tier(model, prompt_tokens)
    return (inp * t["input"] + cw * t["cache_write_5m"] + cr * t["cache_read"] + out * t["output"]) / 1_000_000


def worst_case_cost(model: str, est_input_tokens: int, max_tokens: int) -> float:
    """Upper bound for one call: every input token at the most expensive input rate,
    and max_tokens of output. est_input_tokens must itself be an upper bound."""
    t = _tier(model, est_input_tokens)
    input_rate = max(t["input"], t["cache_write_5m"], t["cache_write_1h"])
    return (est_input_tokens * input_rate + max_tokens * t["output"]) / 1_000_000


class CostTracker:
    def __init__(self, model: str, log_path: Path | None = None, budget: float = config.BUDGET_USD,
                 run_id: str | None = None, run_budget: float = config.RUN_BUDGET_USD):
        if model not in config.PRICING:
            raise ValueError(f"no pricing in config.PRICING for model {model!r}")
        self.model = model
        self.budget = budget
        self.log_path = Path(log_path) if log_path else default_log_path(model)
        self.total_usd = 0.0          # all runs, from the log
        self.run_total_usd = 0.0      # this run only
        self.calls = 0
        self.task_id = None
        self.run_id = run_id
        self.run_budget = run_budget
        if self.log_path.exists():
            for line in self.log_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    entry = json.loads(line)
                    self.total_usd = entry["running_total_usd"]
                    self.calls += 1
                    if self.run_id is not None and entry.get("run_id") == self.run_id:
                        self.run_total_usd += entry["cost_usd"]

    def set_task(self, task_id: str | None) -> None:
        self.task_id = task_id

    def set_run(self, run_id: str | None, run_budget: float = config.RUN_BUDGET_USD) -> None:
        """Start labelling entries with run_id. The run total is read from the log, so a
        resumed run continues its own count."""
        self.run_id = run_id
        self.run_budget = run_budget
        self.run_total_usd = 0.0
        if run_id is not None and self.log_path.exists():
            for line in self.log_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    entry = json.loads(line)
                    if entry.get("run_id") == run_id:
                        self.run_total_usd += entry["cost_usd"]

    def guard(self, est_input_tokens: int, max_tokens: int, step: int | None = None) -> float:
        """Raise BudgetExceeded if one more call could take the overall total over
        BUDGET_USD, or this run's total over RUN_BUDGET_USD. Returns the worst-case cost."""
        worst = worst_case_cost(self.model, est_input_tokens, max_tokens)
        if self.total_usd + worst > self.budget:
            raise BudgetExceeded(self.total_usd, worst, self.budget, task_id=self.task_id, step=step,
                                 scope="overall", run_id=self.run_id)
        if self.run_id is not None and self.run_total_usd + worst > self.run_budget:
            raise BudgetExceeded(self.run_total_usd, worst, self.run_budget, task_id=self.task_id,
                                 step=step, scope="run", run_id=self.run_id)
        return worst

    def record(self, step: int | None, usage: dict, returned_model: str | None = None) -> dict:
        """Log one call. usage is the dict of usage fields from the response.
        returned_model is response.model, the model ID the API reports serving the call
        (None if the response did not carry one)."""
        cost = cost_of_usage(self.model, usage)
        self.total_usd += cost
        self.run_total_usd += cost
        self.calls += 1
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "model": self.model,
            "returned_model": returned_model,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "step": step,
            "input_tokens": usage.get("input_tokens") or 0,
            "output_tokens": usage.get("output_tokens") or 0,
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens") or 0,
            "cache_read_input_tokens": usage.get("cache_read_input_tokens") or 0,
            "cost_usd": round(cost, 8),
            "running_total_usd": round(self.total_usd, 8),
        }
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(entry) + "\n")
        return entry
