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
    DIVERGENCE_LOOKBACK,
    DIVERGENCE_MIN_PEAK_GAP,
    DIVERGENCE_PRICE_PCT,
    EMA_FAST,
    EMA_SLOW,
    MA_PERIODS,
    MACD_SIGNAL,
    PEAK_PROMINENCE_PCT,
)


@dataclass
class Divergence:
    kind: Literal["top", "bottom"]
    prev_idx: int
    curr_idx: int
    price_prev: float
    price_curr: float
    dif_prev: float
    dif_curr: float


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

    return out


def detect_divergence(df: pd.DataFrame) -> Divergence | None:
    """Look at the last DIVERGENCE_LOOKBACK bars; return latest top or bottom
    divergence between the two most recent confirmed price peaks (or valleys)."""
    if len(df) < DIVERGENCE_LOOKBACK:
        return None

    window = df.tail(DIVERGENCE_LOOKBACK).reset_index(drop=True)
    close = window["close"].to_numpy()
    dif = window["dif"].to_numpy()
    if np.isnan(dif).any():
        return None

    avg_close = float(np.nanmean(close))
    prom = avg_close * PEAK_PROMINENCE_PCT

    top = _check_divergence(close, dif, prom, kind="top")
    if top is not None:
        return top
    return _check_divergence(close, dif, prom, kind="bottom")


def _check_divergence(
    close: np.ndarray, dif: np.ndarray, prominence: float, kind: str
) -> Divergence | None:
    series = close if kind == "top" else -close
    peaks, _ = find_peaks(series, prominence=prominence, distance=DIVERGENCE_MIN_PEAK_GAP)
    if len(peaks) < 2:
        return None
    prev_idx, curr_idx = int(peaks[-2]), int(peaks[-1])

    price_prev, price_curr = float(close[prev_idx]), float(close[curr_idx])
    dif_prev, dif_curr = float(dif[prev_idx]), float(dif[curr_idx])

    if kind == "top":
        # 頂背離：價創新高 (>=2%) but DIF lower
        if price_curr >= price_prev * (1 + DIVERGENCE_PRICE_PCT) and dif_curr < dif_prev:
            return Divergence("top", prev_idx, curr_idx, price_prev, price_curr, dif_prev, dif_curr)
    else:
        # 底背離：價創新低 (>=2%) but DIF higher
        if price_curr <= price_prev * (1 - DIVERGENCE_PRICE_PCT) and dif_curr > dif_prev:
            return Divergence("bottom", prev_idx, curr_idx, price_prev, price_curr, dif_prev, dif_curr)
    return None
