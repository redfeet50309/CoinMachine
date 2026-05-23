"""Tests for scripts/notify.py — LINE Messaging API push module.

Focus on PURE LOGIC (categorize, normalize, state update, format).
No HTTP calls (those are tested manually by --dry-run).
"""

import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from notify import (  # noqa: E402
    _categorize,
    _consec_suffix,
    _format_message,
    _normalize_alert_key,
    _shorten_alert_for_display,
    _update_state,
)


# ---------- _categorize ----------

def test_categorize_quiet():
    assert _categorize([]) == "quiet"


def test_categorize_alert_priority_over_long():
    # Has both a long signal AND an alert — alert wins
    assert _categorize([
        "今日：MA 黃金交叉 (MA5 上穿 MA20)",      # long keyword
        "⚠ 量價背離:漲勢動能衰退 (頂部警訊)",      # alert
    ]) == "alert"


def test_categorize_long_keywords():
    assert _categorize(["今日：MA 黃金交叉 (MA5 上穿 MA20)"]) == "long"
    assert _categorize(["今日：布林 突破上軌 (強多)"]) == "long"
    assert _categorize(["今日：布林 上穿中軌 (買進)"]) == "long"
    assert _categorize(["今日：區間做多 (下軌支撐)"]) == "long"
    assert _categorize(["均線多頭向上發散"]) == "long"
    assert _categorize(["今日：做多訊號 (RSI 自超賣反彈)"]) == "long"


def test_categorize_short_keywords():
    assert _categorize(["今日：MA 死亡交叉 (MA5 下穿 MA20)"]) == "short"
    assert _categorize(["今日：布林 跌破下軌 (強空)"]) == "short"
    assert _categorize(["均線空頭向下發散"]) == "short"
    assert _categorize(["今日：做空訊號 (RSI 自超買回檔)"]) == "short"


def test_categorize_alert_keywords():
    assert _categorize(["⚠ 量價背離:漲勢動能衰退 (頂部警訊)"]) == "alert"
    assert _categorize(["⚡ 量價背離:量增低承接 (反轉訊號)"]) == "alert"
    assert _categorize(["⚠ 量價背離:強烈賣壓殺出"]) == "alert"
    assert _categorize(["今日：MACD 頂背離"]) == "alert"
    assert _categorize(["今日：RSI 底背離"]) == "alert"
    assert _categorize(["布林通道極度收斂 (即將變盤)"]) == "alert"
    assert _categorize(["RSI 高檔鈍化 (強勢可改用 80/20)"]) == "alert"


def test_categorize_recent_divergence_not_alert():
    # 「近期」divergence is stale, should be skipped (then fall through to other tiers)
    # If only "近期頂背離" exists, falls through to "alert" fallback
    # But if has long + 近期 divergence, long wins
    assert _categorize([
        "今日：MA 黃金交叉 (MA5 上穿 MA20)",
        "今日：MACD 近期頂背離",
    ]) == "long"


def test_categorize_fallback_when_unclassified():
    # alerts present but match no keyword — fallback to alert (surfaces unknown)
    assert _categorize(["奇怪的訊號"]) == "alert"


# ---------- _normalize_alert_key ----------

def test_normalize_strips_today_prefix():
    assert _normalize_alert_key("今日：MA 黃金交叉 (MA5 上穿 MA20)") == "MA 黃金交叉 (MA5 上穿 MA20)"
    assert _normalize_alert_key("今日:布林 突破上軌 (強多)") == "布林 突破上軌 (強多)"


def test_normalize_strips_leading_emoji():
    assert _normalize_alert_key("⚠ 量價背離:漲勢動能衰退 (頂部警訊)") == "量價背離:漲勢動能衰退 (頂部警訊)"
    assert _normalize_alert_key("⚡ 量價背離:量增低承接 (反轉訊號)") == "量價背離:量增低承接 (反轉訊號)"


def test_normalize_idempotent():
    """Same alert text on different days normalizes to identical key."""
    k1 = _normalize_alert_key("今日：MACD 頂背離")
    k2 = _normalize_alert_key("今日：MACD 頂背離")
    assert k1 == k2
    assert k1 == "MACD 頂背離"


# ---------- _shorten_alert_for_display ----------

def test_shorten_pv_alert_pulls_paren_label():
    assert _shorten_alert_for_display("⚠ 量價背離:漲勢動能衰退 (頂部警訊)") == "頂部警訊"
    assert _shorten_alert_for_display("⚡ 量價背離:量增低承接 (反轉訊號)") == "反轉訊號"


def test_shorten_ma_cross_drops_detail():
    assert _shorten_alert_for_display("今日：MA 黃金交叉 (MA5 上穿 MA20)") == "MA 黃金交叉"


def test_shorten_ma_spread():
    assert _shorten_alert_for_display("均線多頭向上發散") == "MA多頭發散"
    assert _shorten_alert_for_display("均線空頭向下發散") == "MA空頭發散"


def test_shorten_rsi_numbing():
    assert _shorten_alert_for_display("RSI 高檔鈍化 (強勢可改用 80/20)") == "RSI高檔鈍化"


def test_shorten_bb_squeeze():
    assert _shorten_alert_for_display("布林通道極度收斂 (即將變盤)") == "布林極度收斂"


# ---------- _consec_suffix ----------

def test_consec_suffix_one_day_empty():
    assert _consec_suffix(1) == ""


def test_consec_suffix_multi_day():
    assert _consec_suffix(2) == "(連2日)"
    assert _consec_suffix(5) == "(連5日)"


# ---------- _update_state ----------

def test_update_state_fresh_signals_start_at_one():
    state = _update_state({}, {"8299": ["今日：MA 黃金交叉 (MA5 上穿 MA20)"]}, "2026-05-22T22:00")
    assert state["stocks"]["8299"]["alerts"]["MA 黃金交叉 (MA5 上穿 MA20)"] == 1


def test_update_state_continuing_signal_increments():
    prev = {
        "stocks": {
            "8299": {"alerts": {"量價背離:漲勢動能衰退 (頂部警訊)": 1}}
        }
    }
    new = _update_state(
        prev,
        {"8299": ["⚠ 量價背離:漲勢動能衰退 (頂部警訊)"]},
        "2026-05-23T22:00",
    )
    assert new["stocks"]["8299"]["alerts"]["量價背離:漲勢動能衰退 (頂部警訊)"] == 2


def test_update_state_drops_signal_no_longer_active():
    prev = {
        "stocks": {
            "8299": {"alerts": {
                "量價背離:漲勢動能衰退 (頂部警訊)": 2,
                "MA 黃金交叉 (MA5 上穿 MA20)": 3,
            }}
        }
    }
    # Today only has the 頂部警訊; the MA cross alert is gone
    new = _update_state(
        prev,
        {"8299": ["⚠ 量價背離:漲勢動能衰退 (頂部警訊)"]},
        "2026-05-23T22:00",
    )
    assert "MA 黃金交叉 (MA5 上穿 MA20)" not in new["stocks"]["8299"]["alerts"]
    assert new["stocks"]["8299"]["alerts"]["量價背離:漲勢動能衰退 (頂部警訊)"] == 3


def test_update_state_empty_alerts_excludes_stock():
    # Stock that had alerts yesterday but none today → removed from state entirely
    prev = {"stocks": {"8299": {"alerts": {"X": 1}}}}
    new = _update_state(prev, {}, "2026-05-23T22:00")
    assert "8299" not in new["stocks"]


def test_update_state_records_timestamp():
    new = _update_state({}, {}, "2026-05-23T22:00:00+08:00")
    assert new["last_updated"] == "2026-05-23T22:00:00+08:00"


# ---------- _format_message ----------

def _empty_groups():
    return {"alert": [], "long": [], "short": [], "quiet": []}


def test_format_quiet_day_short():
    groups = _empty_groups()
    groups["quiet"] = [{"id": "8299", "alerts": [], "change_pct": 1.5}] * 5
    msg = _format_message(groups, {"stocks": {}}, {"8299": "群聯"}, date(2026, 5, 22))
    assert "今日 5 支股票皆無事件" in msg
    assert "CoinMachine" in msg
    assert msg.startswith("📊 CoinMachine 5/22(五) 收盤")
    # Quiet-day shortcut should not include the section headers
    assert "━━━" not in msg


def test_format_with_alerts_shows_sections():
    groups = _empty_groups()
    groups["alert"] = [{
        "id": "8299", "change_pct": 4.1,
        "alerts": ["⚠ 量價背離:漲勢動能衰退 (頂部警訊)"],
    }]
    groups["long"] = [{
        "id": "8039", "change_pct": 8.6,
        "alerts": ["今日：布林 突破上軌 (強多)"],
    }]
    groups["quiet"] = [{"id": "2368", "alerts": [], "change_pct": 0.1}]
    state = {"stocks": {
        "8299": {"alerts": {"量價背離:漲勢動能衰退 (頂部警訊)": 1}},
        "8039": {"alerts": {"布林 突破上軌 (強多)": 1}},
    }}
    names = {"8299": "群聯", "8039": "台虹", "2368": "金像電"}
    msg = _format_message(groups, state, names, date(2026, 5, 22))

    assert "━━━ ⚠ 注意 (1) ━━━" in msg
    assert "━━━ 📈 進場 (1) ━━━" in msg
    assert "━━━ 🔍 無事件 (1) ━━━" in msg
    assert "🔴 8299 群聯" in msg
    assert "🟢 8039 台虹" in msg
    assert "+4.1%" in msg
    assert "頂部警訊" in msg
    # Single-day alert → no 連N日 suffix
    assert "連" not in msg.split("頂部警訊")[1].split("\n")[0]


def test_format_shows_consec_suffix_for_multi_day():
    groups = _empty_groups()
    groups["alert"] = [{
        "id": "8299", "change_pct": 4.1,
        "alerts": ["⚠ 量價背離:漲勢動能衰退 (頂部警訊)"],
    }]
    state = {"stocks": {"8299": {"alerts": {"量價背離:漲勢動能衰退 (頂部警訊)": 3}}}}
    msg = _format_message(groups, state, {"8299": "群聯"}, date(2026, 5, 22))
    assert "頂部警訊(連3日)" in msg


def test_format_includes_website_link():
    groups = _empty_groups()
    groups["quiet"] = [{"id": "8299", "alerts": []}]
    msg = _format_message(groups, {}, {"8299": "群聯"}, date(2026, 5, 22))
    assert "redfeet50309.github.io/CoinMachine" in msg


def test_format_weekday_correct():
    # 2026-05-22 is Friday → 五
    groups = _empty_groups()
    msg_fri = _format_message(groups, {}, {}, date(2026, 5, 22))
    assert "5/22(五)" in msg_fri

    # 2026-05-23 is Saturday → 六
    msg_sat = _format_message(groups, {}, {}, date(2026, 5, 23))
    assert "5/23(六)" in msg_sat


def test_format_multiple_alerts_indented_correctly():
    groups = _empty_groups()
    groups["alert"] = [{
        "id": "3236", "change_pct": 5.2,
        "alerts": [
            "⚠ 量價背離:漲勢動能衰退 (頂部警訊)",
            "均線多頭向上發散",
            "RSI 高檔鈍化 (強勢可改用 80/20)",
        ],
    }]
    state = {"stocks": {"3236": {"alerts": {
        "量價背離:漲勢動能衰退 (頂部警訊)": 2,
        "均線多頭向上發散": 5,
        "RSI 高檔鈍化 (強勢可改用 80/20)": 1,
    }}}}
    msg = _format_message(groups, state, {"3236": "千如"}, date(2026, 5, 22))

    assert "頂部警訊(連2日)" in msg
    assert "MA多頭發散(連5日)" in msg
    assert "RSI高檔鈍化" in msg
    # Multiple alerts within a stock use ・ separator after first
    assert "   ・" in msg


def test_format_length_reasonable_for_real_watchlist():
    """10-stock realistic watchlist should fit in 1500 chars."""
    groups = {
        "alert": [
            {"id": "8299", "change_pct": 4.1, "alerts": ["⚠ 量價背離:漲勢動能衰退 (頂部警訊)"]},
            {"id": "3236", "change_pct": 5.2, "alerts": [
                "⚠ 量價背離:漲勢動能衰退 (頂部警訊)",
                "均線多頭向上發散",
            ]},
            {"id": "2301", "change_pct": 1.8, "alerts": ["⚠ 量價背離:漲勢動能衰退 (頂部警訊)"]},
        ],
        "long": [
            {"id": "8039", "change_pct": 8.6, "alerts": ["今日：布林 突破上軌 (強多)"]},
            {"id": "3105", "change_pct": 0.5, "alerts": ["今日：布林 上穿中軌 (買進)"]},
        ],
        "short": [
            {"id": "2605", "change_pct": 2.3, "alerts": ["均線空頭向下發散"]},
        ],
        "quiet": [
            {"id": "2368", "alerts": []},
            {"id": "2449", "alerts": []},
            {"id": "3131", "alerts": []},
            {"id": "3135", "alerts": []},
        ],
    }
    names = {sid: sid for sid in ("8299", "3236", "2301", "8039", "3105", "2605",
                                  "2368", "2449", "3131", "3135")}
    state = {"stocks": {}}
    msg = _format_message(groups, state, names, date(2026, 5, 22))
    assert len(msg) < 1500
    assert len(msg) < 5000  # LINE limit
