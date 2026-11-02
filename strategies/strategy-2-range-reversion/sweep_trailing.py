"""
Validation pass for the capped-stop + trailing-stop change: grid search over
max_loss_pct and trail_atr_mult, train/test split, out-of-sample check on the
top combos, and a sensitivity sweep around the winner — same rigor as every
other parameter change in this project, applied to the newest one.
"""
import json
from dataclasses import replace
import pandas as pd

from strategy import Params
from optimize import run_pooled, grid_search, rank_results, flag_winrate_traps, evaluate_out_of_sample, sensitivity_report

TICKERS = [
    "F", "T", "PLTR", "SOFI", "NIO", "AAL", "CCL", "PBR", "KGC", "GRAB",
    "RIG", "VALE", "WBD", "UAA", "OPEN", "CLSK", "RIOT", "MARA", "AMCR", "KVUE",
    "HBAN", "KEY", "CFG", "RF", "NCLH", "UAL", "DKNG", "LYFT", "PARA", "SIRI",
]
OUT = "output"

base = Params()  # already carries adx_max=25, range_score_min=0.50, min_touches=2, etc.

print("=== Baseline (max_loss_pct=0.006, trail_atr_mult=1.0), train split ===")
_, baseline_train = run_pooled(TICKERS, base, "train")
print(json.dumps(baseline_train, indent=2, default=str))

print("\n=== Grid: max_loss_pct x trail_atr_mult, train split ===")
grid = {
    "max_loss_pct": [0.004, 0.006, 0.008, 0.010],
    "trail_atr_mult": [0.5, 1.0, 1.5, 2.0],
}
results = grid_search(TICKERS, grid, base)
results.to_csv(f"{OUT}/trailing_grid_results.csv", index=False)

ranked = rank_results(results, min_trades=15)
cols = ["max_loss_pct", "trail_atr_mult", "total_trades", "win_rate", "expectancy_pct", "profit_factor", "avg_r"]
print(f"\nTop 10 by expectancy (min 15 trades), {len(ranked)} qualifying of {len(results)} combos:")
print(ranked[cols].head(10).to_string(index=False))

trap = flag_winrate_traps(results, baseline_train["expectancy_pct"] or 0, min_trades=15)
print(f"\nWin-rate traps flagged: {len(trap)}")
if len(trap):
    print(trap[cols].head(5).to_string(index=False))

print("\n=== Out-of-sample check on top 5 ===")
top_rows = ranked.head(5)
top_params = [replace(base, max_loss_pct=row["max_loss_pct"], trail_atr_mult=row["trail_atr_mult"])
              for _, row in top_rows.iterrows()]
oos = evaluate_out_of_sample(TICKERS, top_params)
for i, (_, row) in enumerate(top_rows.iterrows()):
    oos.loc[i, "max_loss_pct"] = row["max_loss_pct"]
    oos.loc[i, "trail_atr_mult"] = row["trail_atr_mult"]
oos.to_csv(f"{OUT}/trailing_out_of_sample.csv", index=False)
print(oos.to_string(index=False))

print("\n=== Sensitivity around baseline ===")
sweeps = {
    "max_loss_pct": [0.003, 0.004, 0.006, 0.008, 0.010, 0.015],
    "trail_atr_mult": [0.5, 0.75, 1.0, 1.5, 2.0, 3.0],
}
sens = sensitivity_report(TICKERS, base, sweeps)
sens.to_csv(f"{OUT}/trailing_sensitivity.csv", index=False)
print(sens[["parameter", "value", "total_trades", "win_rate", "expectancy_pct", "profit_factor"]].to_string(index=False))

print("\nDone.")
