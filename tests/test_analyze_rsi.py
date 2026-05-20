"""Tests for RSI-related helpers in analyze.py."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from analyze import (  # noqa: E402
    _rsi_numbing,
    _rsi_reversal_strategy,
    _rsi_zone,
    analyze,
)
from indicators import Divergence  # noqa: E402


def _row(**kw):
    return pd.Series(kw)


def _df(rows):
    return pd.DataFrame(rows)


# ---------- _rsi_zone ----------

def test_rsi_zone_overbought():
    assert _rsi_zone(_row(rsi=72)) == "超買 (>70)"


def test_rsi_zone_oversold():
    assert _rsi_zone(_row(rsi=25)) == "超賣 (<30)"


def test_rsi_zone_neutral_inclusive_bounds():
    assert _rsi_zone(_row(rsi=70)) == "中性"  # boundary 70 not OB (uses >)
    assert _rsi_zone(_row(rsi=30)) == "中性"
    assert _rsi_zone(_row(rsi=50)) == "中性"


def test_rsi_zone_nan_data_insufficient():
    assert _rsi_zone(_row(rsi=float("nan"))) == "資料不足"


def test_rsi_zone_missing_key_data_insufficient():
    assert _rsi_zone(_row()) == "資料不足"


# ---------- _rsi_numbing ----------

def _numbing_rows(rsi_values, close_values):
    return [{"rsi": r, "close": c} for r, c in zip(rsi_values, close_values)]


def test_rsi_numbing_high_zone_with_new_high():
    # RSI > 70 for last 3 bars AND close is 5-day max
    rows = _numbing_rows(
        rsi_values=[50, 60, 75, 78, 80],
        close_values=[100, 102, 104, 105, 108],  # 108 == max
    )
    assert _rsi_numbing(_df(rows)) == "高檔鈍化"


def test_rsi_numbing_low_zone_with_new_low():
    rows = _numbing_rows(
        rsi_values=[50, 40, 25, 22, 18],
        close_values=[100, 95, 90, 88, 85],  # 85 == min
    )
    assert _rsi_numbing(_df(rows)) == "低檔鈍化"


def test_rsi_numbing_high_not_triggered_when_price_not_new_high():
    # RSI > 70 for last 3 bars but today's close is NOT 5-day high
    rows = _numbing_rows(
        rsi_values=[50, 60, 75, 78, 80],
        close_values=[100, 105, 110, 108, 109],  # 109 < 110 (5-day max)
    )
    assert _rsi_numbing(_df(rows)) is None


def test_rsi_numbing_not_triggered_when_rsi_drops_back_in_window():
    # Only 2 of last 3 bars above 70 → not enough
    rows = _numbing_rows(
        rsi_values=[80, 82, 68, 75, 78],
        close_values=[100, 102, 103, 105, 106],
    )
    assert _rsi_numbing(_df(rows)) is None


def test_rsi_numbing_returns_none_when_too_short():
    rows = _numbing_rows(rsi_values=[80, 82], close_values=[100, 101])
    assert _rsi_numbing(_df(rows)) is None


def test_rsi_numbing_returns_none_when_rsi_nan_in_window():
    # NaN within the last RSI_NUMB_BARS window blocks numbing
    rows = _numbing_rows(
        rsi_values=[80, 80, 80, float("nan"), 80],
        close_values=[100, 101, 102, 103, 104],
    )
    assert _rsi_numbing(_df(rows)) is None


# ---------- _rsi_reversal_strategy ----------

def _strategy_df(t_rsi, y_rsi, close, ma20, macd_zone, macd_cross=None):
    rows = [
        {"rsi": y_rsi, "close": close - 1, "ma20": ma20},
        {"rsi": t_rsi, "close": close, "ma20": ma20},
    ]
    signals = {"macd_zone": macd_zone, "macd_cross": macd_cross}
    return _rsi_reversal_strategy(_df(rows), signals)


def test_rsi_long_strategy_triggers_on_oversold_bounce():
    # Yesterday RSI 28 (< 30); today RSI 40 ∈ [30, 50]; MACD bullish; close > MA20
    out = _strategy_df(t_rsi=40, y_rsi=28, close=105, ma20=100,
                       macd_zone="零軸之上 (多頭)")
    assert out == "做多訊號 (RSI 自超賣反彈)"


def test_rsi_long_strategy_triggers_on_golden_cross_only():
    # MACD zone is divergent but golden cross fires → still long signal
    out = _strategy_df(t_rsi=40, y_rsi=28, close=105, ma20=100,
                       macd_zone="分歧",
                       macd_cross="黃金交叉 (弱反彈)")
    assert out == "做多訊號 (RSI 自超賣反彈)"


def test_rsi_long_strategy_blocked_when_close_below_ma20():
    out = _strategy_df(t_rsi=40, y_rsi=28, close=99, ma20=100,
                       macd_zone="零軸之上 (多頭)")
    assert out is None


def test_rsi_long_strategy_blocked_when_macd_bearish():
    out = _strategy_df(t_rsi=40, y_rsi=28, close=105, ma20=100,
                       macd_zone="零軸之下 (空頭)")
    assert out is None


def test_rsi_long_strategy_not_triggered_when_yesterday_already_in_zone():
    # Yesterday RSI 35 (already in transit zone), today 40 → not transition
    out = _strategy_df(t_rsi=40, y_rsi=35, close=105, ma20=100,
                       macd_zone="零軸之上 (多頭)")
    assert out is None


def test_rsi_short_strategy_triggers_on_overbought_pullback():
    out = _strategy_df(t_rsi=65, y_rsi=72, close=95, ma20=100,
                       macd_zone="零軸之下 (空頭)")
    assert out == "做空訊號 (RSI 自超買回檔)"


def test_rsi_short_strategy_blocked_when_close_above_ma20():
    out = _strategy_df(t_rsi=65, y_rsi=72, close=105, ma20=100,
                       macd_zone="零軸之下 (空頭)")
    assert out is None


def test_rsi_short_strategy_via_death_cross():
    out = _strategy_df(t_rsi=65, y_rsi=72, close=95, ma20=100,
                       macd_zone="分歧",
                       macd_cross="死亡交叉 (強)")
    assert out == "做空訊號 (RSI 自超買回檔)"


def test_rsi_strategy_none_when_nan_rsi():
    rows = [
        {"rsi": float("nan"), "close": 100, "ma20": 100},
        {"rsi": 40, "close": 105, "ma20": 100},
    ]
    sig = {"macd_zone": "多頭", "macd_cross": None}
    assert _rsi_reversal_strategy(_df(rows), sig) is None


def test_rsi_strategy_none_when_single_row():
    rows = [{"rsi": 40, "close": 100, "ma20": 100}]
    sig = {"macd_zone": "多頭", "macd_cross": None}
    assert _rsi_reversal_strategy(_df(rows), sig) is None


# ---------- analyze() integration with RSI ----------

def test_analyze_emits_rsi_zone_and_numbing():
    rows = []
    # 10 rows ending with sustained overbought + new high
    for i in range(10):
        rows.append({
            "close": 100 + i * 2,
            "ma5": 100, "ma20": 100, "ma60": 100,
            "dif": 0.5, "macd": 0.4, "osc": 0.1,
            "rsi": 50 if i < 5 else 80,
        })
    out = analyze(_df(rows), None)
    sig = out["signals"]
    assert sig["rsi_zone"] == "超買 (>70)"
    assert sig["rsi_numbing"] == "高檔鈍化"
    assert any("高檔鈍化" in a for a in out["alerts"])


def test_analyze_emits_rsi_strategy_alert():
    # Build enough rows; last two days are the transition (RSI bounces from
    # 25 to 40, MACD bullish, close > MA20).
    rows = []
    for i in range(10):
        rows.append({
            "close": 100 + i,
            "ma5": 100, "ma20": 105, "ma60": 100,
            "dif": 0.5, "macd": 0.3, "osc": 0.2,
            "rsi": 50,
        })
    # Yesterday: oversold
    rows[-2] = {**rows[-2], "rsi": 25, "close": 108}
    # Today: bounce into 30-50 zone, MACD bullish, close > MA20
    rows[-1] = {**rows[-1], "rsi": 40, "close": 110}
    out = analyze(_df(rows), None)
    assert out["signals"]["rsi_strategy"] == "做多訊號 (RSI 自超賣反彈)"
    assert any("做多訊號" in a for a in out["alerts"])


def test_analyze_emits_rsi_divergence_alert_today():
    rows = []
    for i in range(70):
        rows.append({
            "close": 100, "ma5": 100, "ma20": 100, "ma60": 100,
            "dif": 0.5, "macd": 0.4, "osc": 0.1, "rsi": 50,
        })
    div = Divergence(
        kind="top", prev_idx=10, curr_idx=59,
        price_prev=100.0, price_curr=105.0,
        indicator_prev=72.0, indicator_curr=68.0, source="rsi",
    )
    out = analyze(_df(rows), None, rsi_divergence=div)
    assert out["signals"]["rsi_divergence"] == "頂背離"
    assert any("RSI 頂背離" in a for a in out["alerts"])


def test_analyze_recent_rsi_divergence_does_not_alert():
    rows = []
    for i in range(70):
        rows.append({
            "close": 100, "ma5": 100, "ma20": 100, "ma60": 100,
            "dif": 0.5, "macd": 0.4, "osc": 0.1, "rsi": 50,
        })
    div = Divergence(
        kind="bottom", prev_idx=5, curr_idx=40,
        price_prev=100.0, price_curr=95.0,
        indicator_prev=28.0, indicator_curr=32.0, source="rsi",
    )
    out = analyze(_df(rows), None, rsi_divergence=div)
    assert out["signals"]["rsi_divergence"] == "近期底背離"
    assert not any("近期" not in a and "底背離" in a and "RSI" in a for a in out["alerts"])
