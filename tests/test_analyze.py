"""Characterization tests for analyze.py.

These tests fix the CURRENT behavior of every helper in analyze.py so future
refactors do not silently change signal output. Any test that breaks during
refactor signals a behavior change that needs intentional review.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from analyze import (  # noqa: E402
    _bb_bandwidth_state,
    _bb_cross,
    _bb_percent_b_zone,
    _bb_range_strategy,
    _bb_zone,
    _direction_streak,
    _ma_cross,
    _ma_trend,
    _macd_cross,
    _macd_histogram,
    _macd_zone,
    _spread_state,
    analyze,
)
from indicators import Divergence  # noqa: E402


def _row(**kwargs):
    return pd.Series(kwargs)


# ---------- _ma_trend ----------

def test_ma_trend_bull():
    assert _ma_trend(_row(ma5=110, ma20=100, ma60=90)) == "多頭排列"


def test_ma_trend_bear():
    assert _ma_trend(_row(ma5=90, ma20=100, ma60=110)) == "空頭排列"


def test_ma_trend_neutral_when_ma5_below_ma20_but_ma60_lower():
    assert _ma_trend(_row(ma5=95, ma20=100, ma60=90)) == "盤整"


def test_ma_trend_data_insufficient_any_nan():
    assert _ma_trend(_row(ma5=float("nan"), ma20=100, ma60=90)) == "資料不足"
    assert _ma_trend(_row(ma5=110, ma20=float("nan"), ma60=90)) == "資料不足"
    assert _ma_trend(_row(ma5=110, ma20=100, ma60=float("nan"))) == "資料不足"


# ---------- _spread_state ----------

def test_spread_state_cluster_below_1_5_pct():
    # max-min spread = 1, close=100, spread_pct = 1% < 1.5%
    assert _spread_state(_row(ma5=100, ma20=99.5, ma60=100), None, 100.0) == "糾結"


def test_spread_state_normal_between_thresholds():
    # spread = 2.0, close=100 → 2% — between 1.5% and 3%
    assert _spread_state(_row(ma5=101, ma20=100, ma60=99), None, 100.0) == "普通"


def test_spread_state_bull_spread_without_slope_anchor():
    # ma5>ma20>ma60, spread 4% > 3%, prev_slope None
    assert _spread_state(_row(ma5=104, ma20=101, ma60=100), None, 100.0) == "多頭發散"


def test_spread_state_bull_spread_up_when_ma5_rising():
    today = _row(ma5=104, ma20=101, ma60=100)
    prev = _row(ma5=102)  # today.ma5 > prev.ma5
    assert _spread_state(today, prev, 100.0) == "向上發散"


def test_spread_state_bear_spread_without_slope_anchor():
    assert _spread_state(_row(ma5=96, ma20=99, ma60=100), None, 100.0) == "空頭發散"


def test_spread_state_bear_spread_down_when_ma5_falling():
    today = _row(ma5=96, ma20=99, ma60=100)
    prev = _row(ma5=98)  # today.ma5 < prev.ma5
    assert _spread_state(today, prev, 100.0) == "向下發散"


def test_spread_state_diverged_but_not_aligned():
    # spread 4%, but order not monotone (ma5 in middle)
    assert _spread_state(_row(ma5=102, ma20=104, ma60=100), None, 100.0) == "發散"


def test_spread_state_data_insufficient():
    assert (
        _spread_state(_row(ma5=float("nan"), ma20=100, ma60=99), None, 100.0)
        == "資料不足"
    )


def test_spread_state_close_zero_falls_to_cluster():
    # close=0 → spread_pct=0 → cluster branch
    assert _spread_state(_row(ma5=100, ma20=99, ma60=98), None, 0) == "糾結"


def test_spread_state_prev_slope_with_nan_ma5_ignored():
    today = _row(ma5=104, ma20=101, ma60=100)
    prev = _row(ma5=float("nan"))
    # Falls back to "多頭發散" because prev ma5 is NaN
    assert _spread_state(today, prev, 100.0) == "多頭發散"


# ---------- _ma_cross ----------

def test_ma_cross_golden_with_anchor_ok():
    today = _row(ma5=101, ma20=100)
    yest = _row(ma5=99, ma20=100)
    anchor = _row(ma20=95)  # t20=100 >= a20=95
    assert _ma_cross(today, yest, anchor) == "黃金交叉 (MA5 上穿 MA20)"


def test_ma_cross_golden_blocked_when_ma20_below_anchor():
    today = _row(ma5=101, ma20=100)
    yest = _row(ma5=99, ma20=100)
    anchor = _row(ma20=105)  # t20=100 < a20=105 → blocked
    assert _ma_cross(today, yest, anchor) is None


def test_ma_cross_death_with_anchor_ok():
    today = _row(ma5=99, ma20=100)
    yest = _row(ma5=101, ma20=100)
    anchor = _row(ma20=105)  # t20=100 <= a20=105
    assert _ma_cross(today, yest, anchor) == "死亡交叉 (MA5 下穿 MA20)"


def test_ma_cross_no_cross():
    today = _row(ma5=105, ma20=100)
    yest = _row(ma5=104, ma20=100)
    assert _ma_cross(today, yest, _row(ma20=99)) is None


def test_ma_cross_data_insufficient():
    today = _row(ma5=float("nan"), ma20=100)
    yest = _row(ma5=99, ma20=100)
    assert _ma_cross(today, yest, _row(ma20=95)) is None


def test_ma_cross_anchor_none_or_nan_still_fires():
    today = _row(ma5=101, ma20=100)
    yest = _row(ma5=99, ma20=100)
    # anchor with NaN ma20 acts as "no filter"
    assert _ma_cross(today, yest, _row(ma20=float("nan"))) == "黃金交叉 (MA5 上穿 MA20)"


# ---------- _macd_zone ----------

def test_macd_zone_above_zero():
    assert _macd_zone(_row(dif=1.0, macd=0.5)) == "零軸之上 (多頭)"


def test_macd_zone_below_zero():
    assert _macd_zone(_row(dif=-1.0, macd=-0.5)) == "零軸之下 (空頭)"


def test_macd_zone_divergent_dif_positive_macd_negative():
    assert _macd_zone(_row(dif=0.5, macd=-0.5)) == "分歧"


def test_macd_zone_data_insufficient():
    assert _macd_zone(_row(dif=float("nan"), macd=0.5)) == "資料不足"


# ---------- _macd_cross ----------

def test_macd_cross_golden_strong_above_zero():
    today = _row(dif=1.2, macd=1.0)
    yest = _row(dif=0.8, macd=1.0)
    assert _macd_cross(today, yest, ) == "黃金交叉 (強)"


def test_macd_cross_golden_weak_below_zero():
    today = _row(dif=-0.8, macd=-1.0)
    yest = _row(dif=-1.2, macd=-1.0)
    # crossed_up but not both > 0
    assert _macd_cross(today, yest) == "黃金交叉 (弱反彈)"


def test_macd_cross_death_strong_below_zero():
    today = _row(dif=-1.2, macd=-1.0)
    yest = _row(dif=-0.8, macd=-1.0)
    assert _macd_cross(today, yest) == "死亡交叉 (強)"


def test_macd_cross_death_weak_above_zero():
    today = _row(dif=0.8, macd=1.0)
    yest = _row(dif=1.2, macd=1.0)
    assert _macd_cross(today, yest) == "死亡交叉 (弱回檔)"


def test_macd_cross_no_cross():
    today = _row(dif=1.2, macd=1.0)
    yest = _row(dif=1.1, macd=1.0)
    assert _macd_cross(today, yest) is None


def test_macd_cross_data_insufficient():
    today = _row(dif=float("nan"), macd=1.0)
    yest = _row(dif=0.8, macd=1.0)
    assert _macd_cross(today, yest) is None


# ---------- _macd_histogram ----------

def test_macd_histogram_too_short():
    assert _macd_histogram(pd.Series([0.5])) is None


def test_macd_histogram_red_flip_from_green():
    # yest <= 0, today > 0 → red flip
    assert _macd_histogram(pd.Series([-0.5, 0.3])) == "紅柱翻揚"


def test_macd_histogram_green_flip_from_red():
    assert _macd_histogram(pd.Series([0.5, -0.3])) == "綠柱翻落"


def test_macd_histogram_red_growing():
    # 紅柱 today > yest, both > 0
    assert _macd_histogram(pd.Series([0.2, 0.4])) == "紅柱變長"


def test_macd_histogram_red_shrinking():
    assert _macd_histogram(pd.Series([0.4, 0.2])) == "紅柱縮短"


def test_macd_histogram_red_flat():
    assert _macd_histogram(pd.Series([0.3, 0.3])) == "紅柱持平"


def test_macd_histogram_green_growing_more_negative():
    # today more negative than yest → 綠柱變長
    assert _macd_histogram(pd.Series([-0.2, -0.4])) == "綠柱變長"


def test_macd_histogram_green_shrinking_less_negative():
    assert _macd_histogram(pd.Series([-0.4, -0.2])) == "綠柱縮短"


def test_macd_histogram_zero_today_returns_none():
    assert _macd_histogram(pd.Series([0.3, 0.0])) is None


def test_macd_histogram_streak_suffix_trend_3_days():
    # 連續變長 3 日，達 OSC_TREND_BARS=3 但未到 5
    series = pd.Series([0.1, 0.2, 0.3])
    out = _macd_histogram(series)
    assert out == "紅柱變長 (連3日)"


def test_macd_histogram_streak_suffix_strong_5_days():
    series = pd.Series([0.1, 0.2, 0.3, 0.4, 0.5])
    out = _macd_histogram(series)
    assert out == "紅柱變長 (連5日)"


def test_macd_histogram_dropna_works():
    # NaN should be dropped before evaluation
    series = pd.Series([float("nan"), 0.2, 0.3])
    assert _macd_histogram(series) == "紅柱變長"


# ---------- _direction_streak ----------

def test_direction_streak_single_day():
    assert _direction_streak(pd.Series([0.3]), "紅柱變長") == 1


def test_direction_streak_breaks_on_color_change():
    # 0.3 -> -0.1: color flip terminates streak
    s = pd.Series([0.3, -0.1])
    assert _direction_streak(s, "綠柱變長") == 1


def test_direction_streak_counts_consecutive_same_state():
    s = pd.Series([0.1, 0.2, 0.3, 0.4])  # 3 transitions of 紅柱變長
    assert _direction_streak(s, "紅柱變長") == 4


def test_direction_streak_breaks_when_state_diverges():
    # last transition is 紅柱縮短 (0.4 -> 0.3), prior is 紅柱變長
    s = pd.Series([0.1, 0.2, 0.4, 0.3])
    assert _direction_streak(s, "紅柱縮短") == 2


# ---------- analyze (integration) ----------

def _build_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_analyze_empty_df():
    out = analyze(pd.DataFrame(), None)
    assert out == {"signals": {}, "alerts": []}


def test_analyze_minimum_signals_present():
    # Two-row frame with sane values — anchors will be None
    rows = [
        {"close": 100, "ma5": 100, "ma20": 100, "ma60": 100,
         "dif": 0.5, "macd": 0.3, "osc": 0.2, "rsi": 50},
        {"close": 101, "ma5": 101, "ma20": 100.5, "ma60": 100,
         "dif": 0.6, "macd": 0.4, "osc": 0.2, "rsi": 55},
    ]
    out = analyze(_build_df(rows), None)
    sig = out["signals"]
    assert sig["ma_trend"] == "多頭排列"
    assert sig["macd_zone"] == "零軸之上 (多頭)"
    assert sig["macd_cross"] is None
    # ma_cross requires trend_anchor lookback > MA_CROSS_TREND_LOOKBACK, so None here
    assert sig["ma_cross"] is None
    assert sig["macd_divergence"] is None


def test_analyze_alert_for_bull_upward_divergence():
    # Build enough rows to satisfy MA_SLOPE_LOOKBACK=3 anchor (need >3 rows for prev_slope)
    rows = []
    for i in range(10):
        rows.append({
            "close": 100 + i,
            "ma5": 100 + i * 1.5,
            "ma20": 100 + i * 1.0,
            "ma60": 100 + i * 0.5,
            "dif": 0.5,
            "macd": 0.3,
            "osc": 0.2,
            "rsi": 50,
        })
    out = analyze(_build_df(rows), None)
    assert out["signals"]["ma_trend"] == "多頭排列"
    assert out["signals"]["ma_spread_state"] == "向上發散"
    assert "均線多頭向上發散" in out["alerts"]


def test_analyze_divergence_today_alert():
    rows = []
    for i in range(70):
        rows.append({
            "close": 100,
            "ma5": 100, "ma20": 100, "ma60": 100,
            "dif": 0.5, "macd": 0.4, "osc": 0.1,
            "rsi": 50,
        })
    df = _build_df(rows)
    # curr_idx must equal len(df.tail(60)) - 1 == 59 (so this is "today")
    div = Divergence(
        kind="top", prev_idx=10, curr_idx=59,
        price_prev=100.0, price_curr=105.0,
        indicator_prev=2.0, indicator_curr=1.0,
    )
    out = analyze(df, div)
    assert out["signals"]["macd_divergence"] == "頂背離"
    assert any("頂背離" in a for a in out["alerts"])


def test_analyze_divergence_recent_does_not_alert():
    rows = []
    for i in range(70):
        rows.append({
            "close": 100, "ma5": 100, "ma20": 100, "ma60": 100,
            "dif": 0.5, "macd": 0.4, "osc": 0.1,
            "rsi": 50,
        })
    df = _build_df(rows)
    # curr_idx != 59 → "近期頂背離", not in alerts
    div = Divergence(
        kind="bottom", prev_idx=5, curr_idx=40,
        price_prev=100.0, price_curr=95.0,
        indicator_prev=-2.0, indicator_curr=-1.0,
    )
    out = analyze(df, div)
    assert out["signals"]["macd_divergence"] == "近期底背離"
    assert not any("底背離" in a and not a.startswith("近期") for a in out["alerts"])


def test_analyze_macd_cross_emits_alert():
    rows = [
        {"close": 100, "ma5": 100, "ma20": 100, "ma60": 100,
         "dif": 0.8, "macd": 1.0, "osc": -0.2, "rsi": 50},
        {"close": 101, "ma5": 100, "ma20": 100, "ma60": 100,
         "dif": 1.2, "macd": 1.0, "osc": 0.2, "rsi": 52},
    ]
    out = analyze(_build_df(rows), None)
    assert out["signals"]["macd_cross"] == "黃金交叉 (強)"
    assert any("MACD 黃金交叉" in a for a in out["alerts"])


# ---------- _bb_zone ----------

def _bb_row(close, upper=110, mid=100, lower=90):
    return _row(close=close, bb_upper=upper, bb_middle=mid, bb_lower=lower)


def test_bb_zone_above_upper():
    assert _bb_zone(_bb_row(115)) == "上軌之上"


def test_bb_zone_bull_range():
    assert _bb_zone(_bb_row(105)) == "多頭區間"


def test_bb_zone_bear_range():
    assert _bb_zone(_bb_row(95)) == "空頭區間"


def test_bb_zone_below_lower():
    assert _bb_zone(_bb_row(85)) == "下軌之下"


def test_bb_zone_on_middle_falls_to_bear():
    # close == middle goes to "空頭區間" (close > mid is False, close >= lower is True)
    assert _bb_zone(_bb_row(100)) == "空頭區間"


def test_bb_zone_data_insufficient():
    assert _bb_zone(_row(close=100, bb_upper=float("nan"), bb_middle=100, bb_lower=90)) == "資料不足"


# ---------- _bb_cross ----------

def _bb_pair(yc, tc, upper=110, mid=100, lower=90):
    today = _row(close=tc, bb_upper=upper, bb_middle=mid, bb_lower=lower)
    yest = _row(close=yc, bb_upper=upper, bb_middle=mid, bb_lower=lower)
    return today, yest


def test_bb_cross_break_upper_strong_bull():
    today, yest = _bb_pair(yc=109, tc=111)
    assert _bb_cross(today, yest) == "突破上軌 (強多)"


def test_bb_cross_break_lower_strong_bear():
    today, yest = _bb_pair(yc=91, tc=89)
    assert _bb_cross(today, yest) == "跌破下軌 (強空)"


def test_bb_cross_up_through_middle():
    today, yest = _bb_pair(yc=99, tc=101)
    assert _bb_cross(today, yest) == "上穿中軌 (買進)"


def test_bb_cross_down_through_middle():
    today, yest = _bb_pair(yc=101, tc=99)
    assert _bb_cross(today, yest) == "下穿中軌 (放空)"


def test_bb_cross_up_through_lower():
    # yest was BELOW lower, today >= lower (but still < middle)
    today, yest = _bb_pair(yc=89, tc=91)
    assert _bb_cross(today, yest) == "上穿下軌 (空頭轉弱)"


def test_bb_cross_down_through_upper():
    today, yest = _bb_pair(yc=111, tc=109)
    assert _bb_cross(today, yest) == "下穿上軌 (多頭轉弱)"


def test_bb_cross_no_event():
    # both days well inside the bull range, no boundary crossed
    today, yest = _bb_pair(yc=104, tc=105)
    assert _bb_cross(today, yest) is None


def test_bb_cross_priority_gap_up_breaks_upper():
    # Big gap from below lower past upper. Multiple crosses satisfied;
    # 突破上軌 has top priority.
    today, yest = _bb_pair(yc=85, tc=115)
    assert _bb_cross(today, yest) == "突破上軌 (強多)"


def test_bb_cross_priority_gap_down_breaks_lower():
    today, yest = _bb_pair(yc=115, tc=85)
    assert _bb_cross(today, yest) == "跌破下軌 (強空)"


def test_bb_cross_data_insufficient_returns_none():
    today, yest = _bb_pair(yc=99, tc=101, upper=float("nan"))
    assert _bb_cross(today, yest) is None


# ---------- _bb_percent_b_zone ----------

def test_bb_percent_b_super_bull_over_100():
    assert _bb_percent_b_zone(_row(percent_b=1.05)) == "超強多 (>100%)"


def test_bb_percent_b_bull_80_to_100():
    assert _bb_percent_b_zone(_row(percent_b=0.85)) == "多頭 (≥80%)"


def test_bb_percent_b_neutral_middle_range():
    assert _bb_percent_b_zone(_row(percent_b=0.5)) == "中性"


def test_bb_percent_b_bear_below_20():
    assert _bb_percent_b_zone(_row(percent_b=0.10)) == "空頭 (≤20%)"


def test_bb_percent_b_super_bear_negative():
    assert _bb_percent_b_zone(_row(percent_b=-0.05)) == "超強空 (<0%)"


def test_bb_percent_b_boundary_at_80_is_bull():
    assert _bb_percent_b_zone(_row(percent_b=0.80)) == "多頭 (≥80%)"


def test_bb_percent_b_boundary_at_20_is_neutral_strict():
    # > 0.20 is neutral; == 0.20 falls into bear band
    assert _bb_percent_b_zone(_row(percent_b=0.20)) == "空頭 (≤20%)"


def test_bb_percent_b_data_insufficient():
    assert _bb_percent_b_zone(_row(percent_b=float("nan"))) == "資料不足"


# ---------- _bb_bandwidth_state ----------

def test_bb_bandwidth_extreme_squeeze():
    assert _bb_bandwidth_state(_row(bandwidth=0.02)) == "極度收斂"


def test_bb_bandwidth_squeeze():
    assert _bb_bandwidth_state(_row(bandwidth=0.07)) == "收斂"


def test_bb_bandwidth_normal():
    assert _bb_bandwidth_state(_row(bandwidth=0.15)) == "正常"


def test_bb_bandwidth_data_insufficient():
    assert _bb_bandwidth_state(_row(bandwidth=float("nan"))) == "資料不足"


def test_bb_bandwidth_per_stock_extreme():
    # bw below this stock's p5 → 極度收斂 (個股 p5)
    today = _row(bandwidth=0.04, bandwidth_pct20=0.08, bandwidth_pct05=0.05)
    assert _bb_bandwidth_state(today) == "極度收斂 (個股 p5)"


def test_bb_bandwidth_per_stock_squeeze():
    # bw between p5 and p20 → 收斂 (個股 p20)
    today = _row(bandwidth=0.07, bandwidth_pct20=0.08, bandwidth_pct05=0.05)
    assert _bb_bandwidth_state(today) == "收斂 (個股 p20)"


def test_bb_bandwidth_per_stock_normal():
    # bw above p20 → 正常 (even if globally below 0.10 squeeze)
    today = _row(bandwidth=0.09, bandwidth_pct20=0.08, bandwidth_pct05=0.05)
    assert _bb_bandwidth_state(today) == "正常"


def test_bb_bandwidth_falls_back_to_global_when_pct_nan():
    # Per-stock thresholds NaN (warmup) → global thresholds apply
    today = _row(bandwidth=0.07, bandwidth_pct20=float("nan"), bandwidth_pct05=float("nan"))
    assert _bb_bandwidth_state(today) == "收斂"  # global: 0.07 < 0.10
    today2 = _row(bandwidth=0.02, bandwidth_pct20=float("nan"), bandwidth_pct05=float("nan"))
    assert _bb_bandwidth_state(today2) == "極度收斂"


def test_bb_bandwidth_falls_back_when_pct_keys_missing():
    # No pct columns at all (older data) → global thresholds
    today = _row(bandwidth=0.07)
    assert _bb_bandwidth_state(today) == "收斂"


# ---------- analyze (BB integration) ----------

def test_analyze_bb_keys_present_with_data():
    rows = [
        {"close": 99, "ma5": 100, "ma20": 100, "ma60": 100,
         "dif": 0, "macd": 0, "osc": 0, "rsi": 50,
         "bb_upper": 110, "bb_middle": 100, "bb_lower": 90,
         "percent_b": 0.45, "bandwidth": 0.20},
        {"close": 101, "ma5": 100, "ma20": 100, "ma60": 100,
         "dif": 0, "macd": 0, "osc": 0, "rsi": 50,
         "bb_upper": 110, "bb_middle": 100, "bb_lower": 90,
         "percent_b": 0.55, "bandwidth": 0.20},
    ]
    out = analyze(_build_df(rows), None)
    sig = out["signals"]
    assert sig["bb_zone"] == "多頭區間"
    assert sig["bb_cross"] == "上穿中軌 (買進)"
    assert sig["bb_percent_b_zone"] == "中性"
    assert sig["bb_bandwidth_state"] == "正常"
    assert any("布林 上穿中軌" in a for a in out["alerts"])


def test_analyze_bb_squeeze_alert():
    rows = [
        {"close": 100, "ma5": 100, "ma20": 100, "ma60": 100,
         "dif": 0, "macd": 0, "osc": 0, "rsi": 50,
         "bb_upper": 100.5, "bb_middle": 100, "bb_lower": 99.5,
         "percent_b": 0.5, "bandwidth": 0.01},
        {"close": 100, "ma5": 100, "ma20": 100, "ma60": 100,
         "dif": 0, "macd": 0, "osc": 0, "rsi": 50,
         "bb_upper": 100.5, "bb_middle": 100, "bb_lower": 99.5,
         "percent_b": 0.5, "bandwidth": 0.01},
    ]
    out = analyze(_build_df(rows), None)
    assert out["signals"]["bb_bandwidth_state"] == "極度收斂"
    assert any("極度收斂" in a for a in out["alerts"])


# ---------- _bb_range_strategy ----------

def _bb_range_signals(spread="糾結", bw_state="正常", cross=None):
    return {"ma_spread_state": spread, "bb_bandwidth_state": bw_state, "bb_cross": cross}


def test_bb_range_long_at_lower_band():
    today = _row(percent_b=0.10)
    assert _bb_range_strategy(today, _bb_range_signals()) == "區間做多 (下軌支撐)"


def test_bb_range_short_at_upper_band():
    today = _row(percent_b=0.90)
    assert _bb_range_strategy(today, _bb_range_signals()) == "區間做空 (上軌壓力)"


def test_bb_range_middle_no_signal():
    today = _row(percent_b=0.50)
    assert _bb_range_strategy(today, _bb_range_signals()) is None


def test_bb_range_blocked_by_active_cross():
    # 即使在區間極端值,若今天 cross 觸發,優先 cross
    today = _row(percent_b=0.10)
    sigs = _bb_range_signals(cross="跌破下軌 (強空)")
    assert _bb_range_strategy(today, sigs) is None


def test_bb_range_blocked_when_squeezing():
    today = _row(percent_b=0.10)
    assert _bb_range_strategy(today, _bb_range_signals(bw_state="收斂")) is None
    assert _bb_range_strategy(today, _bb_range_signals(bw_state="極度收斂")) is None


def test_bb_range_blocked_when_diverging():
    # 趨勢明顯(發散)不適合區間策略
    today = _row(percent_b=0.10)
    assert _bb_range_strategy(today, _bb_range_signals(spread="多頭發散")) is None
    assert _bb_range_strategy(today, _bb_range_signals(spread="空頭發散")) is None
    assert _bb_range_strategy(today, _bb_range_signals(spread="向上發散")) is None


def test_bb_range_allows_normal_spread():
    today = _row(percent_b=0.10)
    assert _bb_range_strategy(today, _bb_range_signals(spread="普通")) == "區間做多 (下軌支撐)"


def test_bb_range_percent_b_nan_returns_none():
    today = _row(percent_b=float("nan"))
    assert _bb_range_strategy(today, _bb_range_signals()) is None


def test_analyze_bb_range_strategy_emits_alert():
    rows = [
        {"close": 99, "ma5": 100, "ma20": 100, "ma60": 100,
         "dif": 0, "macd": 0, "osc": 0, "rsi": 50,
         "bb_upper": 110, "bb_middle": 100, "bb_lower": 90,
         "percent_b": 0.5, "bandwidth": 0.20},
        # today close hits near lower; percent_b = 0.10
        {"close": 91, "ma5": 100, "ma20": 100, "ma60": 100,
         "dif": 0, "macd": 0, "osc": 0, "rsi": 50,
         "bb_upper": 110, "bb_middle": 100, "bb_lower": 90,
         "percent_b": 0.05, "bandwidth": 0.20},
    ]
    out = analyze(_build_df(rows), None)
    # yest <= 90, today 91 → cross "上穿下軌"? Let me check: yest 99 → above lower 90, today 91 → still ≥ lower.
    # That's NOT a cross (#5 requires yest < lower). So bb_cross should be None.
    # ma_spread_state needs 5/20/60 inputs — all 100, spread 0% → 糾結
    assert out["signals"]["bb_cross"] is None
    assert out["signals"]["bb_range_strategy"] == "區間做多 (下軌支撐)"
    assert any("區間做多" in a for a in out["alerts"])


def test_analyze_bb_missing_columns_returns_data_insufficient():
    # Existing minimum_signals_present test omits bb_* — verify graceful degrade.
    rows = [
        {"close": 100, "ma5": 100, "ma20": 100, "ma60": 100,
         "dif": 0.5, "macd": 0.3, "osc": 0.2, "rsi": 50},
        {"close": 101, "ma5": 101, "ma20": 100.5, "ma60": 100,
         "dif": 0.6, "macd": 0.4, "osc": 0.2, "rsi": 55},
    ]
    out = analyze(_build_df(rows), None)
    assert out["signals"]["bb_zone"] == "資料不足"
    assert out["signals"]["bb_cross"] is None
    assert out["signals"]["bb_percent_b_zone"] == "資料不足"
    assert out["signals"]["bb_bandwidth_state"] == "資料不足"
