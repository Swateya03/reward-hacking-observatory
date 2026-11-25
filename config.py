"""
Experiment configuration.

Single source of the run settings. Every result file records the values it
was produced with (see build_result in run_experiment.py), so changing a
value here changes what later runs record, not what earlier runs say.

Override per run with CLI flags where available (run_experiment.py --max-steps).
"""

MAX_STEPS = 20                          # episode step limit (agent/loop.py, run_experiment.py)
MODEL = "claude-sonnet-4-20250514"      # model ID sent to the API
TEMPERATURE = 0.1                       # sampling temperature for the experiment
