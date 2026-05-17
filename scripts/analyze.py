"""Turn indicator DataFrame into human-readable signal strings + alerts."""

from __future__ import annotations

from typing import Any

import pandas as pd

from config import (
    MA_CLUSTER_DAYS,
    MA_CLUSTER_PCT,
    MA_CROSS_TREND_LOOKBACK,
    MA_SLOPE_LOOKBACK,
    MA_SPREAD_PCT,
    OSC_STRONG_BARS,
    OSC_TREND_BARS,
)
from indicators import Divergence


def _spread_state(today: pd.Series, prev_slope: pd.Series | None, close: float) -> str:
    ma5, ma20, ma60 = today.get("ma5"), today.get("ma20"), today.get("ma60")
    if pd.isna(ma5) or pd.isna(ma20) or pd.isna(ma60):
        return "資料不足"

    spread = max(ma5, ma20, ma60) - min(ma5, ma20, ma60)
    spread_pct = spread / close if close else 0

    if spread_pct < MA_CLUSTER_PCT:
        return "糾結"
    if spread_pct > MA_SPREAD_PCT:
        if ma5 > ma20 > ma60:
            if prev_slope is not None and not pd.isna(prev_slope.get("ma5")):
                if today["ma5"] > prev_slope["ma5"]:
                    return "向上發散"
            return "多頭發散"
        if ma5 < ma20 < ma60:
            if prev_slope is not None and not pd.isna(prev_slope.get("ma5")):
                if today["ma5"] < prev_slope["ma5"]:
                    return "向下發散"
            return "空頭發散"
        return "發散"
    return "普通"


def _ma_trend(today: pd.Series) -> str:
    ma5, ma20, ma60 = today.get("ma5"), today.get("ma20"), today.get("ma60")
    if pd.isna(ma5) or pd.isna(ma20) or pd.isna(ma60):
        return "資料不足"
    if ma5 > ma20 > ma60:
        return "多頭排列"
    if ma5 < ma20 < ma60:
        return "空頭排列"
    return "盤整"


def _ma_cross(today: pd.Series, yesterday: pd.Series, trend_anchor: pd.Series) -> str | None:
    """5/20 golden/death cross + 20-MA slope filter."""
    t5, t20 = today.get("ma5"), today.get("ma20")
    y5, y20 = yesterday.get("ma5"), yesterday.get("ma20")
    a20 = trend_anchor.get("ma20") if trend_anchor is not None else None
    if any(pd.isna(x) for x in (t5, t20, y5, y20)):
        return None

    crossed_up = y5 <= y20 and t5 > t20
    crossed_dn = y5 >= y20 and t5 < t20

    if crossed_up and (a20 is None or pd.isna(a20) or t20 >= a20):
        return "黃金交叉 (5/20)"
    if crossed_dn and (a20 is None or pd.isna(a20) or t20 <= a20):
        return "死亡交叉 (5/20)"
    return None


def _macd_zone(today: pd.Series) -> str:
    dif, macd = today.get("dif"), today.get("macd")
    if pd.isna(dif) or pd.isna(macd):
        return "資料不足"
    if dif > 0 and macd > 0:
        return "零軸之上 (多頭)"
    if dif < 0 and macd < 0:
        return "零軸之下 (空頭)"
    return "分歧"


def _macd_cross(today: pd.Series, yesterday: pd.Series) -> str | None:
    t_dif, t_macd = today.get("dif"), today.get("macd")
    y_dif, y_macd = yesterday.get("dif"), yesterday.get("macd")
    if any(pd.isna(x) for x in (t_dif, t_macd, y_dif, y_macd)):
        return None

    crossed_up = y_dif <= y_macd and t_dif > t_macd
    crossed_dn = y_dif >= y_macd and t_dif < t_macd

    if crossed_up:
        return "黃金交叉 (強)" if t_dif > 0 and t_macd > 0 else "黃金交叉 (弱反彈)"
    if crossed_dn:
        return "死亡交叉 (強)" if t_dif < 0 and t_macd < 0 else "死亡交叉 (弱回檔)"
    return None


def _macd_histogram(osc_tail: pd.Series) -> str | None:
    osc_tail = osc_tail.dropna()
    if len(osc_tail) < OSC_TREND_BARS:
        return None

    today_osc = osc_tail.iloc[-1]
    last_n = osc_tail.iloc[-OSC_TREND_BARS:]
    last_strong = osc_tail.iloc[-OSC_STRONG_BARS:] if len(osc_tail) >= OSC_STRONG_BARS else None
    color = "紅柱" if today_osc > 0 else ("綠柱" if today_osc < 0 else None)
    if color is None:
        return None

    # Compare absolute magnitude for green bars (deeper = stronger)
    series = last_n if today_osc > 0 else -last_n
    increasing = series.is_monotonic_increasing and series.iloc[-1] > series.iloc[0]
    decreasing = series.is_monotonic_decreasing and series.iloc[-1] < series.iloc[0]

    if increasing:
        if last_strong is not None:
            strong_series = last_strong if today_osc > 0 else -last_strong
            if strong_series.is_monotonic_increasing and strong_series.iloc[-1] > strong_series.iloc[0]:
                return f"{color}強加速"
        return f"{color}加速"
    if decreasing:
        return f"{color}減弱"
    return None


def analyze(df: pd.DataFrame, divergence: Divergence | None) -> dict[str, Any]:
    """Return latest signals dict + alerts list.

    df must be sorted by date and contain MA/MACD columns from indicators.compute_indicators.
    """
    if df.empty:
        return {"signals": {}, "alerts": []}

    today = df.iloc[-1]
    yesterday = df.iloc[-2] if len(df) >= 2 else today

    trend_anchor_idx = -1 - MA_CROSS_TREND_LOOKBACK
    trend_anchor = df.iloc[trend_anchor_idx] if len(df) > MA_CROSS_TREND_LOOKBACK else None

    prev_slope_idx = -1 - MA_SLOPE_LOOKBACK
    prev_slope = df.iloc[prev_slope_idx] if len(df) > MA_SLOPE_LOOKBACK else None

    close = today.get("close")

    signals = {
        "ma_trend": _ma_trend(today),
        "ma_cross": _ma_cross(today, yesterday, trend_anchor) if trend_anchor is not None else None,
        "ma_spread_state": _spread_state(today, prev_slope, close),
        "macd_zone": _macd_zone(today),
        "macd_cross": _macd_cross(today, yesterday),
        "macd_histogram": _macd_histogram(df["osc"]),
        "macd_divergence": None,
    }

    if divergence and divergence.curr_idx == len(df.tail(60)) - 1:
        signals["macd_divergence"] = "頂背離" if divergence.kind == "top" else "底背離"
    elif divergence:
        # Persisting divergence (recent but not today)
        signals["macd_divergence"] = (
            "近期頂背離" if divergence.kind == "top" else "近期底背離"
        )

    alerts: list[str] = []
    if signals["ma_cross"]:
        alerts.append(f"今日：MA {signals['ma_cross']}")
    if signals["macd_cross"]:
        alerts.append(f"今日：MACD {signals['macd_cross']}")
    if signals["macd_divergence"] and not signals["macd_divergence"].startswith("近期"):
        alerts.append(f"今日：MACD {signals['macd_divergence']}")
    if signals["ma_trend"] == "多頭排列" and signals["ma_spread_state"] == "向上發散":
        alerts.append("均線多頭向上發散")
    if signals["ma_trend"] == "空頭排列" and signals["ma_spread_state"] == "向下發散":
        alerts.append("均線空頭向下發散")

    return {"signals": signals, "alerts": alerts}
