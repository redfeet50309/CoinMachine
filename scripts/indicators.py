"""MA, EMA, MACD, and peak-based divergence detection.

EMA uses pandas ewm(adjust=False), matching the common Taiwanese brokerage
convention where each EMA value is computed recursively from the previous one
starting at the first close (no front-loaded SMA seed). With span N, the weight
of the seed shrinks below 1% after ~5×N bars, so leaving warmup_months at 18
gives stable values for MA240 / EMA26 by the time output starts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd
from scipy.signal import find_peaks

from config import (
    BB_PERIOD,
    BB_STD_DDOF,
    BB_STD_MULT,
    DIVERGENCE_LOOKBACK,
    DIVERGENCE_MIN_PEAK_GAP,
    DIVERGENCE_PRICE_PCT,
    EMA_FAST,
    EMA_SLOW,
    MA_PERIODS,
    MACD_SIGNAL,
    PEAK_PROMINENCE_PCT,
    RSI_PERIOD,
)


@dataclass
class Divergence:
    kind: Literal["top", "bottom"]
    prev_idx: int
    curr_idx: int
    price_prev: float
    price_curr: float
    indicator_prev: float
    indicator_curr: float
    source: Literal["macd", "rsi"] = "macd"


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Append MA/EMA/MACD columns to a sorted-by-date DataFrame with close."""
    out = df.copy()
    close = out["close"]

    for p in MA_PERIODS:
        out[f"ma{p}"] = close.rolling(window=p, min_periods=p).mean()

    ema_fast = close.ewm(span=EMA_FAST, adjust=False).mean()
    ema_slow = close.ewm(span=EMA_SLOW, adjust=False).mean()
    out["dif"] = ema_fast - ema_slow
    out["macd"] = out["dif"].ewm(span=MACD_SIGNAL, adjust=False).mean()
    out["osc"] = out["dif"] - out["macd"]

    out["rsi"] = compute_rsi(close, period=RSI_PERIOD)

    # Bollinger Bands: 20-period SMA ± 2σ (population std to match TradingView).
    bb_mid = close.rolling(window=BB_PERIOD, min_periods=BB_PERIOD).mean()
    bb_std = close.rolling(window=BB_PERIOD, min_periods=BB_PERIOD).std(ddof=BB_STD_DDOF)
    out["bb_middle"] = bb_mid
    out["bb_upper"] = bb_mid + BB_STD_MULT * bb_std
    out["bb_lower"] = bb_mid - BB_STD_MULT * bb_std
    bb_range = out["bb_upper"] - out["bb_lower"]
    # Guard against zero band-range (constant series) → NaN instead of div-by-zero.
    out["percent_b"] = (close - out["bb_lower"]) / bb_range.where(bb_range != 0)
    out["bandwidth"] = bb_range / bb_mid.where(bb_mid != 0)

    return out


def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI. Uses ewm(alpha=1/period, adjust=False) to match the
    common Taiwan brokerage convention; first `period` values are NaN.

    Constant input (no price movement) yields NaN (0/0). Pure uptrend yields
    100 (loss = 0); pure downtrend yields 0 (gain = 0).
    """
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
    # avg_loss == 0 → rs = inf → rsi = 100 (correct for pure uptrend)
    # avg_gain == avg_loss == 0 → rs = NaN → rsi stays NaN (flat market)
    rsi = rsi.where(avg_loss != 0, 100.0)
    rsi = rsi.where(~((avg_gain == 0) & (avg_loss == 0)), np.nan)
    return rsi


def detect_divergence(df: pd.DataFrame) -> Divergence | None:
    """Look at the last DIVERGENCE_LOOKBACK bars; return latest MACD top or
    bottom divergence between the two most recent confirmed price peaks
    (or valleys)."""
    return _detect_divergence_for(df, "dif", source="macd")


def detect_rsi_divergence(df: pd.DataFrame) -> Divergence | None:
    """RSI variant of detect_divergence — same peak/valley logic on the
    `rsi` column instead of `dif`."""
    return _detect_divergence_for(df, "rsi", source="rsi")


def _detect_divergence_for(
    df: pd.DataFrame, indicator_col: str, source: str
) -> Divergence | None:
    if len(df) < DIVERGENCE_LOOKBACK:
        return None
    window = df.tail(DIVERGENCE_LOOKBACK).reset_index(drop=True)
    close = window["close"].to_numpy()
    indicator = window[indicator_col].to_numpy()
    if np.isnan(indicator).any():
        return None

    avg_close = float(np.nanmean(close))
    prom = avg_close * PEAK_PROMINENCE_PCT

    top = _check_divergence(close, indicator, prom, kind="top", source=source)
    if top is not None:
        return top
    return _check_divergence(close, indicator, prom, kind="bottom", source=source)


def _check_divergence(
    close: np.ndarray,
    indicator: np.ndarray,
    prominence: float,
    kind: str,
    source: str = "macd",
) -> Divergence | None:
    series = close if kind == "top" else -close
    peaks, _ = find_peaks(series, prominence=prominence, distance=DIVERGENCE_MIN_PEAK_GAP)
    if len(peaks) < 2:
        return None
    prev_idx, curr_idx = int(peaks[-2]), int(peaks[-1])

    price_prev, price_curr = float(close[prev_idx]), float(close[curr_idx])
    ind_prev, ind_curr = float(indicator[prev_idx]), float(indicator[curr_idx])

    if kind == "top":
        # 頂背離：價創新高 (>=2%) but indicator lower
        if price_curr >= price_prev * (1 + DIVERGENCE_PRICE_PCT) and ind_curr < ind_prev:
            return Divergence("top", prev_idx, curr_idx,
                              price_prev, price_curr, ind_prev, ind_curr, source)
    else:
        # 底背離：價創新低 (>=2%) but indicator higher
        if price_curr <= price_prev * (1 - DIVERGENCE_PRICE_PCT) and ind_curr > ind_prev:
            return Divergence("bottom", prev_idx, curr_idx,
                              price_prev, price_curr, ind_prev, ind_curr, source)
    return None
