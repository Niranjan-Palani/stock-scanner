"""
Runs the micro-pullback engine (strategy.py) across the watchlist's cached
5-min bars (reusing strategy-2's already-fetched data/ folder — same
tickers, same source) and writes a report.

See strategy.py's module docstring for the scope caveat: this tests the
pullback entry/exit mechanics, not the Five Pillars stock-selection filter
(no float/news data available; this ticker universe is mostly not
low-float names).
"""
import os
import sys
import json
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "strategy-2-range-reversion"))
from data_loader import load_bars, train_test_split, DATA_DIR  # noqa: E402
from metrics import summarize  # noqa: E402
sys.path.pop(0)

sys.path.insert(0, os.path.dirname(__file__))
from strategy import Params, run_backtest  # noqa: E402

WATCHLIST_5MIN = [
    'F', 'T', 'PLTR', 'SOFI', 'NIO', 'AAL', 'CCL', 'PBR', 'KGC', 'GRAB',
    'RIG', 'VALE', 'WBD', 'UAA', 'OPEN', 'CLSK', 'RIOT', 'MARA', 'AMCR', 'KVUE',
    'HBAN', 'KEY', 'CFG', 'RF', 'NCLH', 'UAL', 'DKNG', 'LYFT', 'PARA', 'SIRI',
]
WATCHLIST_1MIN = ['F', 'PLTR', 'SOFI', 'NIO', 'AAL']
WATCHLIST_LOWFLOAT = ['ATER', 'CENN', 'PHUN', 'KOSS', 'BENF', 'SOS', 'SNTI']  # actual float <20M, per filter_universe.py

TIMEFRAME = sys.argv[1] if len(sys.argv) > 1 else "5min"
UNIVERSE_ARG = sys.argv[2] if len(sys.argv) > 2 else "default"
if UNIVERSE_ARG == "lowfloat":
    WATCHLIST = WATCHLIST_LOWFLOAT
    OUT_TAG = "lowfloat"
else:
    WATCHLIST = WATCHLIST_1MIN if TIMEFRAME == "1min" else WATCHLIST_5MIN
    OUT_TAG = TIMEFRAME
OUT_DIR = os.path.join(os.path.dirname(__file__), "output")
OUT_NAME = f"backtest_results_{OUT_TAG}.json"


TF_MINUTES = {"1min": 1, "5min": 5, "15min": 15}[TIMEFRAME]
# scale bar-count windows so they represent the same real-world minutes regardless of timeframe
_SCALE = 5 / TF_MINUTES


def main():
    params = Params(
        squeeze_lookback=max(2, round(6 * _SCALE)),
        max_hold_bars=max(2, round(24 * _SCALE)),
    )
    all_train_trades, all_test_trades = [], []
    per_symbol = {}
    skipped = []

    for sym in WATCHLIST:
        path = os.path.join(DATA_DIR, f"{sym}_{TIMEFRAME}.csv")
        if not os.path.exists(path):
            skipped.append(sym)
            continue
        df = load_bars(sym, interval=TIMEFRAME)
        if len(df) < 100:
            skipped.append(sym)
            continue
        train, test = train_test_split(df, 0.7)

        train_trades, train_equity = run_backtest(train, params, timeframe_minutes=TF_MINUTES)
        test_trades, test_equity = run_backtest(test, params, timeframe_minutes=TF_MINUTES)

        all_train_trades.extend(train_trades)
        all_test_trades.extend(test_trades)
        per_symbol[sym] = {
            "train": summarize(train_trades, train_equity, TF_MINUTES),
            "test": summarize(test_trades, test_equity, TF_MINUTES),
        }

    pooled_train = summarize(all_train_trades, pd.Series(dtype=float), TF_MINUTES)
    pooled_test = summarize(all_test_trades, pd.Series(dtype=float), TF_MINUTES)

    os.makedirs(OUT_DIR, exist_ok=True)
    result = {
        "universe": [s for s in WATCHLIST if s not in skipped],
        "skipped_no_data": skipped,
        "timeframe": TIMEFRAME,
        "params": params.__dict__,
        "pooled_train": pooled_train,
        "pooled_test": pooled_test,
        "per_symbol": per_symbol,
    }
    out_path = os.path.join(OUT_DIR, OUT_NAME)
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2, default=str)

    print(f"Universe: {len(result['universe'])} tickers, {len(skipped)} skipped (no data): {skipped}")
    print("\n=== POOLED TRAIN ===")
    print(json.dumps(pooled_train, indent=2, default=str))
    print("\n=== POOLED TEST ===")
    print(json.dumps(pooled_test, indent=2, default=str))
    print(f"\nFull results written to {out_path}")


if __name__ == "__main__":
    main()
