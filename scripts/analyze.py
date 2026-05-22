"""Turn indicator DataFrame into human-readable signal strings + alerts."""

from __future__ import annotations

from typing import Any

import pandas as pd

from config import (
    BB_BANDWIDTH_EXTREME,
    BB_BANDWIDTH_SQUEEZE,
    BB_PERCENT_B_HIGH,
    BB_PERCENT_B_LOW,
    MA_CLUSTER_DAYS,
    MA_CLUSTER_PCT,
    MA_CROSS_TREND_LOOKBACK,
    MA_SLOPE_LOOKBACK,
    MA_SPREAD_PCT,
    OSC_STRONG_BARS,
    OSC_TREND_BARS,
    RSI_BOUNCE_HIGH,
    RSI_NUMB_BARS,
    RSI_NUMB_PRICE_LOOKBACK,
    RSI_OVERBOUGHT,
    RSI_OVERSOLD,
    RSI_PULLBACK_LOW,
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
        return "黃金交叉 (MA5 上穿 MA20)"
    if crossed_dn and (a20 is None or pd.isna(a20) or t20 <= a20):
        return "死亡交叉 (MA5 下穿 MA20)"
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
    """Day-on-day comparison: every trading day has a state.

    Red bar (OSC > 0): bullish momentum. Higher than yesterday = 變長, lower = 縮短.
    Green bar (OSC < 0): bearish momentum. More negative than yesterday = 變長 (棒子更長),
    less negative = 縮短.
    Color flip (red↔green) gets its own label.
    Bonus: 連 N 日 suffix when the same direction repeats for OSC_TREND_BARS or more.
    """
    osc_tail = osc_tail.dropna()
    if len(osc_tail) < 2:
        return None

    today_osc = float(osc_tail.iloc[-1])
    yest_osc = float(osc_tail.iloc[-2])

    if today_osc > 0:
        color = "紅柱"
        if yest_osc <= 0:
            return f"{color}翻揚"  # green→red flip
        base = f"{color}變長" if today_osc > yest_osc else (f"{color}縮短" if today_osc < yest_osc else f"{color}持平")
    elif today_osc < 0:
        color = "綠柱"
        if yest_osc >= 0:
            return f"{color}翻落"  # red→green flip
        # More negative = bar grew taller
        base = f"{color}變長" if today_osc < yest_osc else (f"{color}縮短" if today_osc > yest_osc else f"{color}持平")
    else:
        return None  # OSC exactly zero

    # Bonus: count consecutive days of the same direction (variant of base)
    streak = _direction_streak(osc_tail, base)
    if streak >= OSC_STRONG_BARS:
        return f"{base} (連{streak}日)"
    if streak >= OSC_TREND_BARS:
        return f"{base} (連{streak}日)"
    return base


def _direction_streak(osc_tail: pd.Series, base_state: str) -> int:
    """Count how many consecutive recent days share today's same-color same-direction state."""
    if len(osc_tail) < 2:
        return 1
    values = osc_tail.to_numpy()
    streak = 1
    for i in range(len(values) - 1, 0, -1):
        today, yest = float(values[i]), float(values[i - 1])
        same_color = (today > 0 and yest > 0) or (today < 0 and yest < 0)
        if not same_color:
            break
        if today > 0:
            day_state = "紅柱變長" if today > yest else ("紅柱縮短" if today < yest else "紅柱持平")
        else:
            day_state = "綠柱變長" if today < yest else ("綠柱縮短" if today > yest else "綠柱持平")
        if day_state != base_state:
            break
        streak += 1
    return streak


def _rsi_zone(today: pd.Series) -> str:
    rsi = today.get("rsi")
    if rsi is None or pd.isna(rsi):
        return "資料不足"
    if rsi > RSI_OVERBOUGHT:
        return f"超買 (>{RSI_OVERBOUGHT})"
    if rsi < RSI_OVERSOLD:
        return f"超賣 (<{RSI_OVERSOLD})"
    return "中性"


def _rsi_numbing(df: pd.DataFrame) -> str | None:
    """High/low-zone numbing: RSI stays in OB/OS zone for >=N bars while close
    keeps making new highs/lows over a wider lookback window."""
    needed = max(RSI_NUMB_BARS, RSI_NUMB_PRICE_LOOKBACK)
    if len(df) < needed:
        return None
    last_rsi = df["rsi"].iloc[-RSI_NUMB_BARS:]
    last_close = df["close"].iloc[-RSI_NUMB_PRICE_LOOKBACK:]
    if last_rsi.isna().any() or last_close.isna().any():
        return None
    today_close = float(last_close.iloc[-1])

    if (last_rsi > RSI_OVERBOUGHT).all() and today_close >= float(last_close.max()):
        return "高檔鈍化"
    if (last_rsi < RSI_OVERSOLD).all() and today_close <= float(last_close.min()):
        return "低檔鈍化"
    return None


def _rsi_reversal_strategy(df: pd.DataFrame, signals: dict[str, Any]) -> str | None:
    """Composite signal fired only on transition day (matches ma_cross style).

    Long  : yesterday RSI < OVERSOLD; today RSI ∈ [OVERSOLD, PULLBACK_LOW];
            MACD in bullish zone OR golden cross; close > MA20.
    Short : yesterday RSI > OVERBOUGHT; today RSI ∈ [BOUNCE_HIGH, OVERBOUGHT];
            MACD in bearish zone OR death cross; close < MA20.
    """
    if len(df) < 2:
        return None
    today = df.iloc[-1]
    yesterday = df.iloc[-2]

    t_rsi, y_rsi = today.get("rsi"), yesterday.get("rsi")
    close, ma20 = today.get("close"), today.get("ma20")
    if any(pd.isna(x) for x in (t_rsi, y_rsi, close, ma20)):
        return None

    macd_zone = signals.get("macd_zone") or ""
    macd_cross = signals.get("macd_cross") or ""

    long_macd_ok = "多頭" in macd_zone or "黃金" in macd_cross
    short_macd_ok = "空頭" in macd_zone or "死亡" in macd_cross

    long_transition = y_rsi < RSI_OVERSOLD and RSI_OVERSOLD <= t_rsi <= RSI_PULLBACK_LOW
    short_transition = y_rsi > RSI_OVERBOUGHT and RSI_BOUNCE_HIGH <= t_rsi <= RSI_OVERBOUGHT

    if long_transition and long_macd_ok and close > ma20:
        return "做多訊號 (RSI 自超賣反彈)"
    if short_transition and short_macd_ok and close < ma20:
        return "做空訊號 (RSI 自超買回檔)"
    return None


def _bb_zone(today: pd.Series) -> str:
    """Positional state of today's close relative to the Bollinger Bands."""
    close = today.get("close")
    upper, mid, lower = today.get("bb_upper"), today.get("bb_middle"), today.get("bb_lower")
    if any(pd.isna(x) for x in (close, upper, mid, lower)):
        return "資料不足"
    if close > upper:
        return "上軌之上"
    if close > mid:
        return "多頭區間"
    if close >= lower:
        return "空頭區間"
    return "下軌之下"


def _bb_cross(today: pd.Series, yesterday: pd.Series) -> str | None:
    """Single highest-priority Bollinger cross event for today.

    Priority (one signal only):
      1 突破上軌 (強多)   — yest ≤ upper AND today > upper
      2 跌破下軌 (強空)   — yest ≥ lower AND today < lower
      3 上穿中軌 (買進)   — yest ≤ mid AND today > mid
      4 下穿中軌 (放空)   — yest ≥ mid AND today < mid
      5 上穿下軌 (空頭轉弱) — yest < lower AND today ≥ lower
      6 下穿上軌 (多頭轉弱) — yest > upper AND today ≤ upper
    """
    tc, yc = today.get("close"), yesterday.get("close")
    tu, tm, tl = today.get("bb_upper"), today.get("bb_middle"), today.get("bb_lower")
    yu, ym, yl = yesterday.get("bb_upper"), yesterday.get("bb_middle"), yesterday.get("bb_lower")
    if any(pd.isna(x) for x in (tc, yc, tu, tm, tl, yu, ym, yl)):
        return None

    if yc <= yu and tc > tu:
        return "突破上軌 (強多)"
    if yc >= yl and tc < tl:
        return "跌破下軌 (強空)"
    if yc <= ym and tc > tm:
        return "上穿中軌 (買進)"
    if yc >= ym and tc < tm:
        return "下穿中軌 (放空)"
    if yc < yl and tc >= tl:
        return "上穿下軌 (空頭轉弱)"
    if yc > yu and tc <= tu:
        return "下穿上軌 (多頭轉弱)"
    return None


def _bb_percent_b_zone(today: pd.Series) -> str:
    """%B classification: <0 / 0–20% / 20–80% / 80–100% / >100%."""
    pb = today.get("percent_b")
    if pb is None or pd.isna(pb):
        return "資料不足"
    if pb > 1.0:
        return "超強多 (>100%)"
    if pb >= BB_PERCENT_B_HIGH:
        return "多頭 (≥80%)"
    if pb > BB_PERCENT_B_LOW:
        return "中性"
    if pb >= 0.0:
        return "空頭 (≤20%)"
    return "超強空 (<0%)"


def _bb_bandwidth_state(today: pd.Series) -> str:
    """Bandwidth classification: <0.03 極度收斂 / <0.10 收斂 / else 正常."""
    bw = today.get("bandwidth")
    if bw is None or pd.isna(bw):
        return "資料不足"
    if bw < BB_BANDWIDTH_EXTREME:
        return "極度收斂"
    if bw < BB_BANDWIDTH_SQUEEZE:
        return "收斂"
    return "正常"


def _divergence_label(div: Divergence | None, df: pd.DataFrame) -> str | None:
    if not div:
        return None
    is_today = div.curr_idx == len(df.tail(60)) - 1
    if is_today:
        return "頂背離" if div.kind == "top" else "底背離"
    return "近期頂背離" if div.kind == "top" else "近期底背離"


def analyze(
    df: pd.DataFrame,
    macd_divergence: Divergence | None,
    rsi_divergence: Divergence | None = None,
) -> dict[str, Any]:
    """Return latest signals dict + alerts list.

    df must be sorted by date and contain MA/MACD/RSI columns from indicators.compute_indicators.
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

    signals: dict[str, Any] = {
        "ma_trend": _ma_trend(today),
        "ma_cross": _ma_cross(today, yesterday, trend_anchor) if trend_anchor is not None else None,
        "ma_spread_state": _spread_state(today, prev_slope, close),
        "macd_zone": _macd_zone(today),
        "macd_cross": _macd_cross(today, yesterday),
        "macd_histogram": _macd_histogram(df["osc"]),
        "macd_divergence": _divergence_label(macd_divergence, df),
        "rsi_zone": _rsi_zone(today),
        "rsi_numbing": _rsi_numbing(df),
        "rsi_divergence": _divergence_label(rsi_divergence, df),
        "rsi_strategy": None,  # filled below — depends on macd_zone/macd_cross
        "bb_zone": _bb_zone(today),
        "bb_cross": _bb_cross(today, yesterday) if len(df) >= 2 else None,
        "bb_percent_b_zone": _bb_percent_b_zone(today),
        "bb_bandwidth_state": _bb_bandwidth_state(today),
    }
    signals["rsi_strategy"] = _rsi_reversal_strategy(df, signals)

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
    if signals["rsi_divergence"] and not signals["rsi_divergence"].startswith("近期"):
        alerts.append(f"今日：RSI {signals['rsi_divergence']}")
    if signals["rsi_numbing"]:
        alerts.append(f"RSI {signals['rsi_numbing']} (強勢可改用 80/20)")
    if signals["rsi_strategy"]:
        alerts.append(f"今日：{signals['rsi_strategy']}")
    if signals["bb_cross"]:
        alerts.append(f"今日：布林 {signals['bb_cross']}")
    if signals["bb_bandwidth_state"] == "極度收斂":
        alerts.append("布林通道極度收斂 (即將變盤)")

    return {"signals": signals, "alerts": alerts}
