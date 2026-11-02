"""
Ross Cameron / Warrior Trading micro-pullback engine — the entry/exit
mechanics half of the strategy (see Obsidian note "Ross Cameron Micro
Pullback Strategy" for full source rules).

IMPORTANT SCOPE NOTE: this backtests the *pullback entry/exit mechanics*
only. The "Five Pillars" stock-selection filter (float <10-20M shares,
news catalyst freshness, up 25%+ on the day) cannot be backtested here —
this data source has no float or news-catalyst history, and the watchlist
itself is mostly large/mid-cap names, not the low-float runners the
strategy is designed around. `squeeze_min_pct` / `squeeze_vol_mult` below
are a same-session proxy for "already up big on high relative volume,"
not a substitute for the real filter. Long-only (the source strategy is
long-only).

Bar-by-bar event loop for the same look-ahead-safety reason as strategy-2:
pullback-count state and squeeze state are path-dependent.
Decision rule at every bar t: only df.iloc[:t+1] is ever read.
"""
from dataclasses import dataclass
import pandas as pd
import numpy as np

import indicators as ind2  # ema (this folder's indicators.py)
from indicators import macd as macd_fn, session_vwap


@dataclass
class Params:
    # squeeze proxy (stand-in for "already up big / high rel volume" pillar — see module docstring)
    squeeze_lookback: int = 6
    squeeze_min_pct: float = 0.03       # +3% over squeeze_lookback bars
    squeeze_vol_mult: float = 1.5       # avg volume over the squeeze vs prior 20-bar avg

    # pullback detection
    max_pullback_bars: int = 2          # only take the 1st or 2nd pullback candle count (per source rules)
    pullback_light_vol_mult: float = 1.0  # pullback bar volume must be <= this * squeeze avg volume

    # confirmation
    require_macd_positive: bool = True
    require_light_red_volume: bool = True

    # risk
    reward_risk_min: float = 2.0        # 2:1 target per source rules
    max_hold_bars: int = 24             # 2h at 5m bars

    fee_bps: float = 1.0
    slippage_bps: float = 2.0

    # Trailing stop: once price reaches the 2:1 target, instead of exiting,
    # arm an ATR-based trailing stop and let the winner run further —
    # same change validated for strategy-2 (trail_atr_mult=2.0 there).
    trail_enabled: bool = True
    trail_atr_mult: float = 2.0


@dataclass
class Trade:
    entry_idx: int
    entry_time: pd.Timestamp
    exit_idx: int = None
    exit_time: pd.Timestamp = None
    direction: str = "long"
    entry_price: float = None
    exit_price: float = None
    stop_price: float = None
    target_price: float = None
    exit_reason: str = None   # "target" | "stop" | "macd_cross" | "below_vwap" | "below_ema9" | "time"
    r_multiple: float = None
    pnl_pct: float = None


def run_backtest(df: pd.DataFrame, params: Params, timeframe_minutes: int = 5) -> tuple[list[Trade], pd.Series]:
    n = len(df)
    highs, lows, closes, opens = df["high"].values, df["low"].values, df["close"].values, df["open"].values
    volumes = df["volume"].values
    times = df.index

    ema9 = ind2.ema(df["close"], 9)
    ema20 = ind2.ema(df["close"], 20)
    macd_line, macd_signal, _ = macd_fn(df["close"])
    vwap = session_vwap(df)
    vol_avg20 = pd.Series(volumes, index=df.index).rolling(20).mean()
    atr_series = ind2.atr(df, 14)

    fee = params.fee_bps / 10000.0
    slip = params.slippage_bps / 10000.0
    min_period = 35  # warm up EMA20/MACD(26)/vol_avg20

    trades: list[Trade] = []
    equity = np.zeros(n)
    equity_val = 0.0

    position = None
    # pullback state
    in_squeeze = False
    pullback_bars = 0
    pullback_low = None
    pullback_vols = []
    squeeze_avg_vol = None
    prior_high = None

    for t in range(min_period, n):
        price = closes[t]

        # 1) manage open position first
        if position is not None:
            bars_held = t - position["entry_idx"]
            exit_now, exit_price, reason = None, None, None
            atr_now = atr_series.iloc[t]
            position["best"] = max(position["best"], highs[t])

            if lows[t] <= position["stop"]:
                exit_now, exit_price, reason = True, position["stop"], "stop"
            elif position["trailing"] and closes[t] < position["trail_stop"]:
                exit_now, exit_price, reason = True, price, "trail"
            elif not position["trailing"] and highs[t] >= position["target"]:
                # reached the 2:1 target: arm a trailing stop instead of a fixed
                # exit, so the winner isn't capped here. Never let the trail sit
                # looser than the original stop — it can only tighten, not widen.
                if params.trail_enabled and not pd.isna(atr_now):
                    position["trailing"] = True
                    position["trail_stop"] = max(position["best"] - params.trail_atr_mult * atr_now, position["stop"])
                else:
                    exit_now, exit_price, reason = True, position["target"], "target"
            elif position["trailing"]:
                new_trail = position["best"] - params.trail_atr_mult * atr_now
                if not pd.isna(new_trail):
                    new_trail = max(new_trail, position["stop"])
                    position["trail_stop"] = max(position["trail_stop"], new_trail)  # ratchets up only
            elif macd_line.iloc[t] < macd_signal.iloc[t] and macd_line.iloc[t - 1] >= macd_signal.iloc[t - 1]:
                exit_now, exit_price, reason = True, price, "macd_cross"
            elif not pd.isna(vwap.iloc[t]) and price < vwap.iloc[t]:
                exit_now, exit_price, reason = True, price, "below_vwap"
            elif not pd.isna(ema9.iloc[t]) and price < ema9.iloc[t]:
                exit_now, exit_price, reason = True, price, "below_ema9"
            elif bars_held >= params.max_hold_bars:
                exit_now, exit_price, reason = True, price, "time"

            if exit_now:
                fill = exit_price * (1 - slip)
                entry_fill = position["entry_price"]
                pnl_pct = (fill - entry_fill) / entry_fill - 2 * fee
                risk_pct = (entry_fill - position["stop"]) / entry_fill
                r_mult = pnl_pct / risk_pct if risk_pct > 0 else 0.0

                tr = position["trade"]
                tr.exit_idx, tr.exit_time = t, times[t]
                tr.exit_price, tr.exit_reason = fill, reason
                tr.pnl_pct, tr.r_multiple = pnl_pct, r_mult
                trades.append(tr)
                equity_val += pnl_pct
                position = None

        equity[t] = equity_val
        if position is not None:
            continue

        # 2) squeeze detection: rolling % move + relative volume over squeeze_lookback bars
        lb = params.squeeze_lookback
        move_pct = closes[t] / closes[t - lb] - 1
        seg_avg_vol = volumes[t - lb + 1:t + 1].mean()
        base_avg_vol = vol_avg20.iloc[t - lb] if not pd.isna(vol_avg20.iloc[t - lb]) else None
        squeeze_now = (
            move_pct >= params.squeeze_min_pct
            and base_avg_vol and seg_avg_vol >= params.squeeze_vol_mult * base_avg_vol
        )

        is_red = closes[t] < opens[t]
        is_green = closes[t] > opens[t]

        if squeeze_now and not in_squeeze:
            in_squeeze = True
            pullback_bars = 0
            pullback_low = None
            pullback_vols = []
            squeeze_avg_vol = seg_avg_vol
            prior_high = highs[t]

        if not in_squeeze:
            continue

        prior_high = max(prior_high, highs[t]) if pullback_bars == 0 else prior_high

        if is_red and pullback_bars < params.max_pullback_bars:
            pullback_bars += 1
            pullback_low = lows[t] if pullback_low is None else min(pullback_low, lows[t])
            pullback_vols.append(volumes[t])
            continue

        # entry trigger: green candle making a new high vs the immediately prior candle's high,
        # after 1-2 pullback candles have printed
        if is_green and 1 <= pullback_bars <= params.max_pullback_bars and highs[t] > highs[t - 1]:
            light_red_ok = True
            if params.require_light_red_volume and pullback_vols and squeeze_avg_vol:
                light_red_ok = np.mean(pullback_vols) <= params.pullback_light_vol_mult * squeeze_avg_vol
            macd_ok = (not params.require_macd_positive) or (
                not pd.isna(macd_line.iloc[t]) and macd_line.iloc[t] > 0 and macd_line.iloc[t] > macd_line.iloc[t - 1]
            )

            if light_red_ok and macd_ok and pullback_low is not None and pullback_low < price:
                entry_price_raw = price
                fill = entry_price_raw * (1 + slip)
                stop = pullback_low
                risk = fill - stop
                if risk > 0:
                    target = fill + params.reward_risk_min * risk
                    trade = Trade(
                        entry_idx=t, entry_time=times[t], entry_price=fill,
                        stop_price=stop, target_price=target,
                    )
                    position = {
                        "entry_idx": t, "entry_price": fill, "stop": stop, "target": target, "trade": trade,
                        "trailing": False, "trail_stop": None, "best": fill,
                    }

            # whether or not the trade fired, this squeeze episode is resolved
            in_squeeze = False
            pullback_bars = 0
            pullback_low = None
            pullback_vols = []
        elif not is_red and pullback_bars == 0:
            # still riding the initial spike, no pullback yet — keep watching
            prior_high = max(prior_high, highs[t])
        elif pullback_bars >= params.max_pullback_bars and not is_green:
            # too many pullback bars without a trigger — squeeze invalidated (per "cautious of 3rd/4th pullback")
            in_squeeze = False
            pullback_bars = 0
            pullback_low = None
            pullback_vols = []

    if position is not None:
        last = n - 1
        tr = position["trade"]
        tr.exit_idx, tr.exit_time = last, times[last]
        tr.exit_price, tr.exit_reason = closes[last], "eod_open"
        entry_fill = position["entry_price"]
        pnl_pct = (tr.exit_price - entry_fill) / entry_fill - 2 * fee
        risk_pct = (entry_fill - position["stop"]) / entry_fill
        tr.pnl_pct = pnl_pct
        tr.r_multiple = pnl_pct / risk_pct if risk_pct > 0 else 0.0
        trades.append(tr)
        equity[-1] = equity_val + pnl_pct

    equity_series = pd.Series(equity, index=df.index)
    return trades, equity_series
