"""Technical indicators (Section 15.1).

Hand-rolled with pandas/numpy for full control and determinism — identical input
always yields identical output (Phase 1 DoD). No dependency on pandas-ta / TA-Lib
so the core feature set installs without the ML extra.

All functions take a bars DataFrame indexed by ts with float columns
``open, high, low, close, volume`` and return a Series (or a feature DataFrame).
Warmup periods are NaN and dropped downstream.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    ranges = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def _wilder(series: pd.Series, period: int) -> pd.Series:
    """Wilder's smoothing (exponential with alpha = 1/period)."""
    return series.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return _wilder(true_range(df), period)


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = _wilder(gain, period)
    avg_loss = _wilder(loss, period)
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    line = ema_fast - ema_slow
    signal_line = line.ewm(span=signal, adjust=False).mean()
    return line, signal_line, line - signal_line


def bollinger_pctb(close: pd.Series, period: int = 20, num_std: float = 2.0) -> pd.Series:
    mid = close.rolling(period).mean()
    sd = close.rolling(period).std()
    upper = mid + num_std * sd
    lower = mid - num_std * sd
    return (close - lower) / (upper - lower)


def donchian_pos(df: pd.DataFrame, period: int = 20) -> pd.Series:
    hi = df["high"].rolling(period).max()
    lo = df["low"].rolling(period).min()
    return (df["close"] - lo) / (hi - lo)


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = np.where((up > down) & (up > 0.0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0.0), down, 0.0)
    plus_dm_s = pd.Series(plus_dm, index=df.index)
    minus_dm_s = pd.Series(minus_dm, index=df.index)
    atr_s = _wilder(true_range(df), period)
    plus_di = 100.0 * _wilder(plus_dm_s, period) / atr_s
    minus_di = 100.0 * _wilder(minus_dm_s, period) / atr_s
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return _wilder(dx, period)


def indicator_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute the technical-indicator feature block."""
    out = pd.DataFrame(index=df.index)
    close = df["close"]
    out["rsi_7"] = rsi(close, 7)
    out["rsi_14"] = rsi(close, 14)
    line, signal_line, hist = macd(close)
    out["macd"] = line
    out["macd_signal"] = signal_line
    out["macd_hist"] = hist
    out["bb_pctb_20"] = bollinger_pctb(close, 20)
    out["donchian_pos_20"] = donchian_pos(df, 20)
    out["adx_14"] = adx(df, 14)
    return out
