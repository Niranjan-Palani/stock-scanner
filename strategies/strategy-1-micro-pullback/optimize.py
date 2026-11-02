"""
Grid search over the micro-pullback engine's key parameters, evaluated on
the train split (pooled across tickers), then checked out-of-sample on the
test split for the top combos — same pattern as strategy-2's optimize.py,
including its overfit-trap flag (looks great on train, collapses on test).
"""
import itertools
import json
import os
import sys
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "strategy-2-range-reversion"))
from data_loader import load_bars, train_test_split, DATA_DIR  # noqa: E402
from metrics import summarize  # noqa: E402
sys.path.pop(0)

sys.path.insert(0, os.path.dirname(__file__))
from strategy import Params, run_backtest  # noqa: E402

UNIVERSE = ['ATER', 'CENN', 'PHUN', 'KOSS', 'BENF', 'SOS', 'SNTI']
TIMEFRAME = "5min"
TF_MINUTES = 5
OUT_PATH = os.path.join(os.path.dirname(__file__), "output", "grid_results.json")

GRID = {
    "squeeze_min_pct": [0.02, 0.03, 0.05],
    "squeeze_vol_mult": [1.2, 1.5, 2.0],
    "pullback_light_vol_mult": [0.8, 1.0, 1.5],
    "reward_risk_min": [1.5, 2.0, 3.0],
}


def load_all_splits():
    data = {}
    for sym in UNIVERSE:
        df = load_bars(sym, interval=TIMEFRAME)
        data[sym] = train_test_split(df, 0.7)
    return data


def run_combo(data, params, split_idx):
    all_trades = []
    for sym, (train, test) in data.items():
        df = train if split_idx == 0 else test
        trades, _ = run_backtest(df, params, timeframe_minutes=TF_MINUTES)
        all_trades.extend(trades)
    return all_trades


def main():
    data = load_all_splits()
    keys = list(GRID.keys())
    combos = list(itertools.product(*GRID.values()))
    print(f"Grid: {len(combos)} combos x {len(UNIVERSE)} tickers")

    results = []
    for combo in combos:
        overrides = dict(zip(keys, combo))
        params = Params(**overrides)
        train_trades = run_combo(data, params, split_idx=0)
        train_summary = summarize(train_trades, pd.Series(dtype=float), TF_MINUTES)
        results.append({"params": overrides, "train": train_summary})

    # rank by train expectancy among combos with a minimally usable sample size
    ranked = sorted(
        [r for r in results if r["train"]["total_trades"] >= 10],
        key=lambda r: r["train"]["expectancy_pct"] or -999,
        reverse=True,
    )

    print(f"\n{len(ranked)}/{len(results)} combos had >=10 train trades")
    top = ranked[:10]

    for r in top:
        overrides = r["params"]
        params = Params(**overrides)
        test_trades = run_combo(data, params, split_idx=1)
        r["test"] = summarize(test_trades, pd.Series(dtype=float), TF_MINUTES)
        train_exp = r["train"]["expectancy_pct"]
        test_exp = r["test"]["expectancy_pct"]
        r["likely_overfit"] = (
            train_exp is not None and test_exp is not None and train_exp > 0 and test_exp < 0
        )

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump({"universe": UNIVERSE, "grid": GRID, "top_10_by_train_expectancy": top,
                   "all_results_count": len(results)}, f, indent=2, default=str)

    print("\n=== TOP 10 BY TRAIN EXPECTANCY (with test/OOS check) ===")
    for r in top:
        t, te = r["train"], r.get("test", {})
        flag = " [LIKELY OVERFIT]" if r.get("likely_overfit") else ""
        print(f"{r['params']}{flag}")
        print(f"  train: {t['total_trades']} trades, wr={t['win_rate']}, exp={t['expectancy_pct']}%, pf={t['profit_factor']}")
        if te:
            print(f"  test:  {te['total_trades']} trades, wr={te['win_rate']}, exp={te['expectancy_pct']}%, pf={te['profit_factor']}")
    print(f"\nFull results written to {OUT_PATH}")


if __name__ == "__main__":
    main()
