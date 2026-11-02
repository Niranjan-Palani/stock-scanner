"""
End-to-end demo: baseline backtest -> grid search -> out-of-sample check ->
sensitivity report -> writes output/report.md and output/*.csv.
"""
import json
import time
import pandas as pd
from dataclasses import replace

from data_loader import load_bars, train_test_split
from strategy import Params, run_backtest
from metrics import summarize
from optimize import run_pooled, grid_search, rank_results, flag_winrate_traps, evaluate_out_of_sample, sensitivity_report

TICKERS = [
    "F", "T", "PLTR", "SOFI", "NIO", "AAL", "CCL", "PBR", "KGC", "GRAB",
    "RIG", "VALE", "WBD", "UAA", "OPEN", "CLSK", "RIOT", "MARA", "AMCR", "KVUE",
    "HBAN", "KEY", "CFG", "RF", "NCLH", "UAL", "DKNG", "LYFT", "PARA", "SIRI",
]
OUT = "output"


def main():
    base = Params()

    print("=== 1. Baseline (default params), pooled across tickers, train split ===")
    _, baseline_train = run_pooled(TICKERS, base, "train")
    print(json.dumps(baseline_train, indent=2, default=str))

    print("\n=== 2. Grid search (regime + tolerance + entry params), train split ===")
    # Narrower grid than the 5-ticker pass — with 30 tickers each combo costs 6x more wall-clock,
    # so this confirms/extends the prior findings (adx 25-30, range_score 0.40-0.55, min_touches 2 vs 3)
    # rather than re-exploring the axes that were already clearly settled (confirm_bars, tolerance_pct).
    grid = {
        "adx_max": [25, 30],
        "range_score_min": [0.40, 0.50, 0.55],
        "min_touches": [2, 3],
        "respect_min": [0.3],
        "tolerance_pct": [0.0015],
        "confirm_bars": [2],
    }
    results = grid_search(TICKERS, grid, base)
    results.to_csv(f"{OUT}/grid_results.csv", index=False)

    ranked = rank_results(results, min_trades=8)
    print(f"\nTop 10 by expectancy (min 8 trades), {len(ranked)} qualifying of {len(results)} combos:")
    cols = ["adx_max", "range_score_min", "min_touches", "respect_min", "tolerance_pct", "confirm_bars",
            "total_trades", "win_rate", "expectancy_pct", "profit_factor", "avg_r"]
    print(ranked[cols].head(10).to_string(index=False))

    trap = flag_winrate_traps(results, baseline_train["expectancy_pct"] or 0, min_trades=8)
    print(f"\nWin-rate traps flagged (higher win% than median but worse expectancy than baseline): {len(trap)}")
    if len(trap):
        print(trap[cols].head(5).to_string(index=False))

    print("\n=== 3. Out-of-sample check on top 5 ranked combos ===")
    top_rows = ranked.head(5)
    top_params = []
    grid_keys = ["adx_max", "range_score_min", "min_touches", "respect_min", "tolerance_pct", "confirm_bars"]
    for _, row in top_rows.iterrows():
        overrides = {k: (int(row[k]) if k == "min_touches" else row[k]) for k in grid_keys}
        top_params.append(replace(base, **overrides))
    oos = evaluate_out_of_sample(TICKERS, top_params)
    for i, (_, row) in enumerate(top_rows.iterrows()):
        for k in grid_keys:
            oos.loc[i, k] = row[k]
    oos.to_csv(f"{OUT}/out_of_sample.csv", index=False)
    print(oos.to_string(index=False))

    print("\n=== 4. Sensitivity sweep around baseline ===")
    sweeps = {
        "adx_max": [15, 20, 25, 30],
        "range_score_min": [0.40, 0.50, 0.60, 0.70],
        "respect_min": [0.2, 0.4, 0.6, 0.8],
        "tolerance_pct": [0.0005, 0.0015, 0.0025, 0.004],
        "min_touches": [2, 3, 4],
        "reversal_confirm_bars": [2, 3, 4, 5],
        "confirm_bars": [1, 2, 3],
        "stop_consecutive_closes": [1, 2, 3],
        "max_hold_bars": [8, 16, 24],  # 2h / 4h / 6h at 15m bars
    }
    sens = sensitivity_report(TICKERS, base, sweeps)
    sens.to_csv(f"{OUT}/sensitivity.csv", index=False)
    print(sens[["parameter", "value", "total_trades", "win_rate", "expectancy_pct", "profit_factor"]].to_string(index=False))

    print("\n=== 5. Optional filters test (session / volume), baseline params otherwise ===")
    for name, override in [
        ("session_filter ON", {"session_filter": True}),
        ("volume_filter ON", {"volume_filter": True}),
        ("both ON", {"session_filter": True, "volume_filter": True}),
    ]:
        params = replace(base, **override)
        _, m = run_pooled(TICKERS, params, "train")
        print(name, "->", {k: m[k] for k in ["total_trades", "win_rate", "expectancy_pct", "profit_factor"]})

    print("\nDone. CSVs written to output/.")


if __name__ == "__main__":
    main()
