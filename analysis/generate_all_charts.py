"""Generate all reward hacking visualization charts."""

import subprocess
import sys

charts = [
    "analysis/charts/chart_divergence_by_ambiguity.py",
    "analysis/charts/chart_hack_types.py",
    "analysis/charts/chart_score_scatter.py",
    "analysis/charts/chart_hack_rate.py",
    "analysis/charts/chart_radar.py",
]

print("\n" + "="*60)
print("GENERATING ALL VISUALIZATION CHARTS")
print("="*60)
print()

succeeded = 0
failed = 0

for chart in charts:
    result = subprocess.run([sys.executable, chart], capture_output=True, text=True)
    chart_name = chart.split("/")[-1].replace(".py", "").replace("chart_", "")

    if result.returncode == 0:
        print(f"[OK] {chart_name}")
        succeeded += 1
    else:
        print(f"[FAILED] {chart_name}")
        print(f"  Error: {result.stderr[:100]}")
        failed += 1

print()
print("="*60)
print(f"RESULTS: {succeeded} succeeded, {failed} failed")
print("="*60)
print()
print("Charts saved to analysis/charts/")
print()
