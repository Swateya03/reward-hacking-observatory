"""
Experiment configuration.

Single source of the run settings. Every result file records the values it
was produced with (see build_result in run_experiment.py), so changing a
value here changes what later runs record, not what earlier runs say.

Override per run with CLI flags where available (run_experiment.py --max-steps).
"""

MAX_STEPS = 20                          # episode step limit (agent/loop.py, run_experiment.py)
MODEL = "claude-haiku-5-5"              # model ID sent to the API (cheaper of the two below)
TEMPERATURE = 0.1                       # sampling temperature for the experiment
MAX_TOKENS = 2048                       # max output tokens per API response; recorded in metadata

# ── Budget ────────────────────────────────────────────────────────────────────
# Hard cap on cumulative API spend across all runs logged in results/runs/<model>/cost_log.jsonl.
# Before each call the client adds the worst-case cost of that call; if the total would exceed
# this cap, the run stops cleanly (agent/cost.py, BudgetExceeded).
BUDGET_USD = 6.50
# Cap for one run (one pass over the task bank, e.g. run_01). Checked alongside BUDGET_USD.
RUN_BUDGET_USD = 2.00

# ── Pricing ───────────────────────────────────────────────────────────────────
# USD per million tokens. Source: https://platform.claude.com/docs/en/about-claude/pricing
# Retrieved 2026-11-25. The page shows no "last updated" date.
# Columns on the page: base input, 5m cache write, 1h cache write, cache hit/refresh, output.
# Haiku 5.5 has two tiers, split by total prompt length (the page counts cache reads and writes too).
PRICING_SOURCE = "https://platform.claude.com/docs/en/about-claude/pricing"
PRICING_RETRIEVED = "2026-11-25"

PRICING = {
    "claude-haiku-5-5": {
        "tiers": [
            # prompts up to 100,000 tokens
            {"max_prompt_tokens": 100_000, "input": 0.10, "cache_write_5m": 0.125,
             "cache_write_1h": 0.20, "cache_read": 0.01, "output": 0.50},
            # prompts over 100,000 tokens
            {"max_prompt_tokens": None, "input": 0.50, "cache_write_5m": 0.625,
             "cache_write_1h": 1.00, "cache_read": 0.05, "output": 2.50},
        ],
    },
    "claude-haiku-4-5-20251001": {
        "tiers": [
            {"max_prompt_tokens": None, "input": 1.00, "cache_write_5m": 1.25,
             "cache_write_1h": 2.00, "cache_read": 0.10, "output": 5.00},
        ],
    },
}

# Per-model request options, from the model pages (checked 2026-11-25):
#   claude-haiku-5-5: https://platform.claude.com/docs/en/models/haiku-5-5/overview
#     "Omit temperature, top_p, and top_k." and "Adaptive thinking is on by default."
#   thinking {"type": "disabled"} is accepted at effort high or below:
#     https://platform.claude.com/docs/en/build-with-claude/thinking
#   (Setting thinking off is a choice made here to control output cost and keep the loop's
#   handling of content blocks valid: thinking blocks would have to be passed back on every
#   tool-use turn. Revisit if the experiment should include thinking.)
# A value of None means: do not send that parameter.
MODEL_OPTIONS = {
    "claude-haiku-5-5": {"temperature": None, "thinking": {"type": "disabled"}},
    "claude-haiku-4-5-20251001": {"temperature": TEMPERATURE, "thinking": None},
}

# Prompt caching: breakpoints go on the last tool definition, the stable system block, and the
# last block of each request. Minimum cacheable prompt (page: "Cache limitations"):
# 512 tokens for Claude Haiku 5.5; 4,096 tokens for Claude Haiku 4.5.
# Source: https://platform.claude.com/docs/en/build-with-claude/prompt-caching
