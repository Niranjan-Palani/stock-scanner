"""Trade-list -> performance metrics."""
import numpy as np
import pandas as pd


def summarize(trades: list, equity: pd.Series, timeframe_minutes: int = 15) -> dict:
    if not trades:
        return {
            "total_trades": 0, "win_rate": None, "avg_r": None, "profit_factor": None,
            "expectancy_pct": None, "max_drawdown_pct": None, "avg_hold_minutes": None,
            "long_trades": 0, "short_trades": 0, "long_win_rate": None, "short_win_rate": None,
        }

    pnl = np.array([t.pnl_pct for t in trades])
    r = np.array([t.r_multiple for t in trades])
    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]
    win_rate = len(wins) / len(pnl)
    profit_factor = (wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() != 0 else float("inf")
    expectancy = pnl.mean()
    hold_bars = np.array([t.exit_idx - t.entry_idx for t in trades])
    avg_hold_minutes = hold_bars.mean() * timeframe_minutes

    longs = [t for t in trades if t.direction == "long"]
    shorts = [t for t in trades if t.direction == "short"]
    long_wr = (sum(1 for t in longs if t.pnl_pct > 0) / len(longs)) if longs else None
    short_wr = (sum(1 for t in shorts if t.pnl_pct > 0) / len(shorts)) if shorts else None

    cum = equity.cummax()
    drawdown = equity - cum
    max_dd = drawdown.min()

    return {
        "total_trades": len(trades),
        "win_rate": round(win_rate, 4),
        "avg_r": round(r.mean(), 4),
        "profit_factor": round(profit_factor, 4) if np.isfinite(profit_factor) else profit_factor,
        "expectancy_pct": round(expectancy * 100, 4),
        "max_drawdown_pct": round(max_dd * 100, 4),
        "avg_hold_minutes": round(avg_hold_minutes, 1),
        "long_trades": len(longs),
        "short_trades": len(shorts),
        "long_win_rate": round(long_wr, 4) if long_wr is not None else None,
        "short_win_rate": round(short_wr, 4) if short_wr is not None else None,
        "exit_reasons": {
            reason: sum(1 for t in trades if t.exit_reason == reason)
            for reason in set(t.exit_reason for t in trades)
        },
    }
