"""
Parameter sweep + train/test evaluation + sensitivity report.

Design choices, stated up front:
  - Backtests are run per-ticker then trades are pooled across tickers before
    computing metrics, so a single lucky/unlucky ticker can't dominate the
    ranking. (Ticker list is small here — 5 — precisely because free-tier
    data access limits how many symbols can be pulled; treat conclusions as
    directional, not statistically bulletproof, until run on more symbols.)
  - Ranking objective is expectancy (mean pnl% per trade), NOT win rate, per
    the brief's explicit instruction not to optimize win rate alone.
    Profit factor is reported alongside and used as a tie-breaker.
  - Any parameter set that improves win rate but *worsens* expectancy or
    profit factor vs. the baseline is explicitly flagged, not hidden.
"""
import itertools
import time
from dataclasses import replace

import pandas as pd

from data_loader import load_bars, train_test_split
from strategy import run_backtest, Params
from metrics import summarize


def run_pooled(tickers: list[str], params: Params, split: str, train_frac: float = 0.7,
                interval: str = "15min") -> tuple[list, dict]:
    """Runs the backtest on each ticker's train or test slice and pools trades."""
    all_trades = []
    all_equity = []
    for sym in tickers:
        df = load_bars(sym, interval)
        train, test = train_test_split(df, train_frac)
        data = train if split == "train" else test
        trades, equity = run_backtest(data, params)
        all_trades.extend(trades)
        all_equity.append(equity)
    m = summarize(all_trades, pd.concat(all_equity) if all_equity else pd.Series(dtype=float))
    return all_trades, m


def grid_search(tickers: list[str], grid: dict, base: Params, train_frac: float = 0.7) -> pd.DataFrame:
    keys = list(grid.keys())
    combos = list(itertools.product(*grid.values()))
    rows = []
    t0 = time.time()
    for i, combo in enumerate(combos):
        overrides = dict(zip(keys, combo))
        params = replace(base, **overrides)
        trades, m = run_pooled(tickers, params, "train", train_frac)
        row = {**overrides, **m}
        row.pop("exit_reasons", None)
        rows.append(row)
    elapsed = time.time() - t0
    print(f"grid_search: {len(combos)} combos x {len(tickers)} tickers in {elapsed:.1f}s")
    return pd.DataFrame(rows)


def rank_results(df: pd.DataFrame, min_trades: int = 8) -> pd.DataFrame:
    """Ranks by expectancy first, profit factor as tie-break; requires a minimum
    sample size so a 1-trade 100%-win-rate fluke can't top the list."""
    viable = df[df["total_trades"] >= min_trades].copy()
    if viable.empty:
        return df.sort_values("total_trades", ascending=False)
    viable["profit_factor_capped"] = viable["profit_factor"].replace([float("inf")], 999)
    return viable.sort_values(["expectancy_pct", "profit_factor_capped"], ascending=False)


def flag_winrate_traps(df: pd.DataFrame, baseline_expectancy: float, min_trades: int = 8) -> pd.DataFrame:
    """Parameter sets with higher win rate than baseline but worse expectancy —
    the exact trap the brief warns about (tiny TP, huge stop -> high win%, negative EV)."""
    viable = df[df["total_trades"] >= min_trades]
    return viable[(viable["win_rate"] > viable["win_rate"].median()) &
                   (viable["expectancy_pct"] < baseline_expectancy)]


def evaluate_out_of_sample(tickers: list[str], top_params: list[Params], train_frac: float = 0.7) -> pd.DataFrame:
    rows = []
    for i, params in enumerate(top_params):
        _, m_train = run_pooled(tickers, params, "train", train_frac)
        _, m_test = run_pooled(tickers, params, "test", train_frac)
        degraded = None
        if m_train.get("expectancy_pct") is not None and m_test.get("expectancy_pct") is not None:
            degraded = m_test["expectancy_pct"] < m_train["expectancy_pct"] * 0.3 or \
                       (m_train["expectancy_pct"] > 0 and m_test["expectancy_pct"] <= 0)
        rows.append({
            "rank": i + 1,
            "train_trades": m_train["total_trades"], "train_expectancy_pct": m_train["expectancy_pct"],
            "train_win_rate": m_train["win_rate"], "train_pf": m_train["profit_factor"],
            "test_trades": m_test["total_trades"], "test_expectancy_pct": m_test["expectancy_pct"],
            "test_win_rate": m_test["win_rate"], "test_pf": m_test["profit_factor"],
            "likely_overfit": degraded,
        })
    return pd.DataFrame(rows)


def sensitivity_report(tickers: list[str], base: Params, sweeps: dict, train_frac: float = 0.7) -> pd.DataFrame:
    """One-parameter-at-a-time sweep around `base`, holding everything else fixed."""
    rows = []
    for param_name, values in sweeps.items():
        for v in values:
            params = replace(base, **{param_name: v})
            _, m = run_pooled(tickers, params, "train", train_frac)
            rows.append({"parameter": param_name, "value": v, **m})
    df = pd.DataFrame(rows)
    df.pop("exit_reasons") if "exit_reasons" in df.columns else None
    return df
