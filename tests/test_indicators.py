"""Verify MA / EMA / MACD math on known fixtures."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from indicators import (  # noqa: E402
    compute_indicators,
    compute_rsi,
    detect_divergence,
    detect_rsi_divergence,
)


def _df(close: list[float]) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=len(close), freq="B").strftime("%Y-%m-%d")
    return pd.DataFrame(
        {
            "date": dates,
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": [1_000_000] * len(close),
        }
    )


def test_ma_constant_series():
    df = _df([100.0] * 30)
    out = compute_indicators(df)
    assert out["ma5"].iloc[-1] == pytest.approx(100.0)
    assert out["ma20"].iloc[-1] == pytest.approx(100.0)


def test_ma_linear_increasing():
    closes = list(range(1, 31))  # 1..30
    df = _df([float(c) for c in closes])
    out = compute_indicators(df)
    # MA5 at index i (0-based) is mean of [i-4 .. i] inclusive
    assert out["ma5"].iloc[4] == pytest.approx(3.0)   # mean(1..5)
    assert out["ma5"].iloc[29] == pytest.approx(28.0)  # mean(26..30)


def test_ema_seed_is_first_close():
    df = _df([10.0, 12.0, 14.0])
    out = compute_indicators(df)
    # ewm adjust=False: first value equals first close
    # DIF = EMA12(close) - EMA26(close); both EMAs seeded at close[0]=10
    # So DIF at index 0 = 10 - 10 = 0
    assert out["dif"].iloc[0] == pytest.approx(0.0, abs=1e-9)


def test_macd_recursive_formula():
    """Hand-trace EMA(2) for verification of recursion math."""
    closes = [10.0, 12.0, 14.0, 16.0]
    df = _df(closes)
    # EMA span=2 → alpha = 2/(2+1) = 2/3
    # ema[0] = 10
    # ema[1] = (1-2/3)*10 + 2/3*12 = 10/3 + 8 = 11.333...
    # ema[2] = (1-2/3)*11.333 + 2/3*14 = 3.778 + 9.333 = 13.111...
    alpha = 2 / 3
    expected = [10.0]
    for c in closes[1:]:
        expected.append((1 - alpha) * expected[-1] + alpha * c)
    actual = df["close"].ewm(span=2, adjust=False).mean().tolist()
    assert actual == pytest.approx(expected, rel=1e-9)


def test_dif_macd_columns_present():
    closes = list(range(1, 100))
    df = _df([float(c) for c in closes])
    out = compute_indicators(df)
    assert "dif" in out.columns
    assert "macd" in out.columns
    assert "osc" in out.columns
    # OSC should equal DIF - MACD
    np.testing.assert_allclose(out["osc"], out["dif"] - out["macd"], rtol=1e-9)


def test_ma_periods_have_nan_during_warmup():
    df = _df([100.0] * 30)
    out = compute_indicators(df)
    assert pd.isna(out["ma240"].iloc[-1])  # not enough data
    assert not pd.isna(out["ma5"].iloc[-1])


def test_divergence_returns_none_when_insufficient_data():
    df = _df([100.0] * 30)
    out = compute_indicators(df)
    assert detect_divergence(out) is None


def test_top_divergence_synthetic():
    """Construct a price series with rising peaks and falling DIF peaks."""
    closes = []
    for i in range(60):
        if i < 20:
            base = 100 + i * 0.5 + (5 if i in (10,) else 0)
        elif i < 40:
            # Rising trend continues
            base = 110 + (i - 20) * 0.3
        else:
            # Peak with higher high but DIF should be lower due to trailing avg
            base = 116 + (i - 40) * 0.6
        closes.append(base + np.sin(i * 0.5))
    df = _df(closes)
    out = compute_indicators(df)
    # Just verify function runs without error on a real-looking series
    result = detect_divergence(out)
    assert result is None or result.kind in ("top", "bottom")


def test_safe_for_small_lookback():
    """Indicators handle short input gracefully."""
    df = _df([100.0, 101.0])
    out = compute_indicators(df)
    assert len(out) == 2
    assert pd.isna(out["ma5"].iloc[-1])


# ---------- RSI ----------

def test_rsi_warmup_first_14_are_nan():
    closes = list(range(1, 31))
    df = _df([float(c) for c in closes])
    out = compute_indicators(df)
    # First 14 values NaN, index 14 onwards has values
    assert pd.isna(out["rsi"].iloc[13])
    assert not pd.isna(out["rsi"].iloc[14])


def test_rsi_pure_uptrend_is_100():
    closes = [float(c) for c in range(1, 50)]
    rsi = compute_rsi(pd.Series(closes), period=14)
    # After warmup, strict uptrend → loss=0 → RSI=100
    assert rsi.iloc[-1] == pytest.approx(100.0)


def test_rsi_pure_downtrend_is_0():
    closes = [float(c) for c in range(50, 0, -1)]
    rsi = compute_rsi(pd.Series(closes), period=14)
    assert rsi.iloc[-1] == pytest.approx(0.0)


def test_rsi_flat_market_is_nan():
    rsi = compute_rsi(pd.Series([100.0] * 30), period=14)
    # No gains, no losses → 0/0 → NaN (no momentum signal possible)
    assert pd.isna(rsi.iloc[-1])


def test_rsi_neutral_zigzag_near_50():
    # Equal-magnitude up/down moves → avg_gain ≈ avg_loss → RSI ≈ 50
    closes = [100.0]
    for i in range(40):
        closes.append(closes[-1] + (1.0 if i % 2 == 0 else -1.0))
    rsi = compute_rsi(pd.Series(closes), period=14)
    assert rsi.iloc[-1] == pytest.approx(50.0, abs=5.0)


def test_rsi_column_added_by_compute_indicators():
    df = _df([float(c) for c in range(1, 50)])
    out = compute_indicators(df)
    assert "rsi" in out.columns
    assert 0 <= out["rsi"].iloc[-1] <= 100


def test_detect_rsi_divergence_returns_none_when_insufficient():
    df = _df([float(c) for c in range(1, 30)])
    out = compute_indicators(df)
    assert detect_rsi_divergence(out) is None


def test_detect_rsi_divergence_runs_on_realistic_series():
    """Smoke test — verify pipeline doesn't crash on a series that may or may
    not contain a divergence."""
    closes = []
    for i in range(80):
        # Two rising peaks
        base = 100 + i * 0.4 + np.sin(i * 0.4) * 3
        closes.append(base)
    df = _df(closes)
    out = compute_indicators(df)
    result = detect_rsi_divergence(out)
    assert result is None or result.kind in ("top", "bottom")
    if result:
        assert result.source == "rsi"
