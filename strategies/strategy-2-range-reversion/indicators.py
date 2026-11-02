"""
Vectorized technical indicators used by the regime filter and level detector.
Every function is causal (uses only data up to and including row t) so nothing
here introduces look-ahead when computed once over the whole DataFrame.
"""
import numpy as np
import pandas as pd


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)

    atr_ = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def efficiency_ratio(close: pd.Series, lookback: int) -> pd.Series:
    net_change = (close - close.shift(lookback)).abs()
    path_length = close.diff().abs().rolling(lookback).sum()
    return (net_change / path_length.replace(0, np.nan)).clip(0, 1)


def bollinger_width(close: pd.Series, period: int = 20, n_std: float = 2.0) -> pd.Series:
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper, lower = mid + n_std * std, mid - n_std * std
    return (upper - lower) / mid.replace(0, np.nan)


def ema_cross_count(close: pd.Series, ema20: pd.Series, lookback: int) -> pd.Series:
    above = (close > ema20).astype(int)
    crosses = above.diff().abs()  # 1 whenever price crosses the EMA
    return crosses.rolling(lookback).sum()
