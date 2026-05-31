"""Daily LINE Messaging API push — broadcasts watchlist summary after build.

Reads data/stocks/*.json (just built by build_dataset.py), categorizes each
stock into 4 groups (注意/進場/空頭/平靜), tracks consecutive-day alert
counts via data/notify_state.json, and pushes a single text message via
the LINE broadcast endpoint (https://api.line.me/v2/bot/message/broadcast).

Token comes from LINE_CHANNEL_ACCESS_TOKEN env var; if unset, the module
no-ops with an info log (so dev / CI runs don't crash).

Direct invocation:
    py scripts/notify.py              # real push (needs token)
    py scripts/notify.py --dry-run    # print message to stdout, no push
    py scripts/notify.py --date=2026-05-22 --dry-run
"""
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

# Windows PowerShell defaults to cp950 on this machine; printing emoji in
# dry-run output crashes with UnicodeEncodeError. Reconfigure stdout/stderr
# to UTF-8 (Python 3.7+ has this method on TextIOWrapper).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

from config import (
    LINE_BROADCAST_URL,
    LINE_CHANNEL_ACCESS_TOKEN,
    WEBSITE_URL,
)

log = logging.getLogger(__name__)
TAIPEI_TZ = timezone(timedelta(hours=8))

# Alert keyword classification — priority: alert > long > short > quiet
# Order within each tuple doesn't matter; first ANY-match in a tier wins the stock.
_ALERT_KEYWORDS = (
    "背離", "頂部警訊", "強烈賣壓", "反轉訊號", "極度收斂", "鈍化",
)
_LONG_KEYWORDS = (
    "黃金交叉", "突破上軌", "上穿中軌", "上穿下軌", "做多訊號",
    "區間做多", "向上發散", "多頭啟動",
)
_SHORT_KEYWORDS = (
    "死亡交叉", "跌破下軌", "下穿中軌", "下穿上軌", "做空訊號",
    "區間做空", "向下發散", "空頭啟動",
)

# Section headers + per-stock dot markers
_CAT_HEADER = {
    "alert": "⚠ 注意",
    "long":  "📈 進場",
    "short": "📉 空頭",
    "quiet": "🔍 無事件",
}
_CAT_DOT = {
    "alert": "🔴",
    "long":  "🟢",
    "short": "🔵",
}

_WEEKDAY_ZH = ["一", "二", "三", "四", "五", "六", "日"]


# ---------- categorization ----------

def _categorize(alerts: list[str]) -> str:
    """alerts list → 'alert' / 'long' / 'short' / 'quiet'.

    Priority: alert > long > short > quiet. Scan all alerts at each tier;
    if any matches, the stock belongs to that tier.

    「近期」divergence (multi-day-old, not today) is too noisy → not counted
    as alert. (Today's divergence has no 「近期」 prefix per analyze.py rules.)
    """
    if not alerts:
        return "quiet"

    # Tier 1: 注意 (warning)
    for a in alerts:
        if "背離" in a and "近期" in a:
            continue  # skip stale divergences
        if a.startswith(("⚠", "⚡")):
            return "alert"
        if any(kw in a for kw in _ALERT_KEYWORDS):
            return "alert"

    # Tier 2: 進場
    for a in alerts:
        if any(kw in a for kw in _LONG_KEYWORDS):
            return "long"

    # Tier 3: 空頭
    for a in alerts:
        if any(kw in a for kw in _SHORT_KEYWORDS):
            return "short"

    # Fallback: alerts present but none classified — surface as alert
    return "alert"


# ---------- alert key normalization (for state tracking) ----------

# Match both half-width ":" (U+003A) and full-width "：" (U+FF1A) — analyze.py
# uses full-width in alert strings (e.g. "今日：MA 黃金交叉").
_TODAY_PREFIX_RE = re.compile(r"^今日[:：]\s*")
_LEADING_EMOJI_RE = re.compile(r"^[⚠⚡✓📈📉🔴🟢🔵🟡⚪]\s*")


def _normalize_alert_key(alert: str) -> str:
    """Stable state-tracking key. Strips 「今日:」prefix and leading emoji.

    Different calendar days of the same signal share the same key, so
    consecutive-day counts work even though the raw alert text day-to-day
    may include 「今日:」 or not.
    """
    s = alert.strip()
    s = _TODAY_PREFIX_RE.sub("", s)
    s = _LEADING_EMOJI_RE.sub("", s)
    return s.strip()


# ---------- alert text → short display label ----------

def _shorten_alert_for_display(alert: str) -> str:
    """Compress alert text for the LINE message body.

    Examples:
      '今日:MA 黃金交叉 (MA5 上穿 MA20)'    → 'MA 黃金交叉'
      '今日:布林 突破上軌 (強多)'           → '布林 突破上軌 (強多)'
      '⚠ 量價背離:漲勢動能衰退 (頂部警訊)'  → '頂部警訊'
      '⚡ 量價背離:量增低承接 (反轉訊號)'   → '反轉訊號'
      '均線多頭向上發散'                   → 'MA多頭發散'
      'RSI 高檔鈍化 (強勢可改用 80/20)'     → 'RSI高檔鈍化'
      '布林通道極度收斂 (即將變盤)'         → '布林極度收斂'
    """
    s = alert.strip()
    s = _TODAY_PREFIX_RE.sub("", s)

    # PV alerts: pull out the (label) suffix
    if s.startswith(("⚠", "⚡")):
        m = re.search(r"\(([^)]+)\)\s*$", s)
        if m:
            return m.group(1).strip()

    s = _LEADING_EMOJI_RE.sub("", s)

    # Common name simplifications
    replacements = [
        ("均線多頭向上發散", "MA多頭發散"),
        ("均線空頭向下發散", "MA空頭發散"),
        ("布林通道極度收斂 (即將變盤)", "布林極度收斂"),
        ("極度收斂 (即將變盤)", "極度收斂"),
    ]
    for old, new in replacements:
        s = s.replace(old, new)

    # Drop verbose trailing parens
    s = re.sub(r"\s*\(強勢可改用 80/20\)\s*$", "", s)
    s = re.sub(r"\s*\(MA[0-9]+ [^)]+\)\s*$", "", s)

    s = s.replace("RSI ", "RSI")
    return s.strip()


# ---------- state file ----------

def _update_state(prev_state: dict, today_alerts: dict[str, list[str]], today_iso: str) -> dict:
    """yesterday state + today's alerts → new state with consecutive-day counts.

    today_alerts maps stock_id → list of (raw) alert texts. Stocks with empty
    alerts are dropped from the new state.
    """
    prev_state = prev_state or {}
    prev_stocks = prev_state.get("stocks", {})

    # Consecutive-day counting is per CALENDAR DAY, not per run. If notify runs
    # more than once on the same date (e.g. a manual test plus the 22:00 cron),
    # don't advance the streak again — otherwise a same-day re-run inflates 連N日.
    prev_date = (prev_state.get("last_updated") or "")[:10]
    same_day = prev_date == today_iso[:10]

    new_stocks: dict[str, dict] = {}

    for sid, alerts in today_alerts.items():
        prev_alerts = prev_stocks.get(sid, {}).get("alerts", {})
        new_alerts: dict[str, int] = {}
        for a in alerts:
            key = _normalize_alert_key(a)
            prev_count = prev_alerts.get(key, 0)
            if same_day:
                # idempotent within a day: keep prior streak; a brand-new alert
                # appearing on a same-day re-run still starts at 1
                new_alerts[key] = prev_count if prev_count > 0 else 1
            else:
                new_alerts[key] = prev_count + 1
        if new_alerts:
            new_stocks[sid] = {"alerts": new_alerts}

    return {
        "last_updated": today_iso,
        "stocks": new_stocks,
    }


def _load_state(state_path: Path) -> dict:
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log.warning("state load failed (%s) — starting fresh", e)
        return {}


def _save_state(state_path: Path, state: dict) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ---------- message formatting ----------

def _consec_suffix(count: int) -> str:
    """'(連N日)' when N >= 2, else ''."""
    return f"(連{count}日)" if count >= 2 else ""


def _format_message(
    grouped: dict[str, list[dict]],
    state: dict,
    watchlist_names: dict[str, str],
    today: date,
    data_date: str | None = None,
) -> str:
    """Compose the LINE message text.

    grouped: {category: [{id, alerts, change_pct}, ...]}
    state:   new state (used for 連N日 suffix per alert)
    """
    # Header shows the actual data (收盤) date; warn if it lags today, which
    # means today's market data hadn't been published when the build ran.
    disp = date.fromisoformat(data_date) if data_date else today
    weekday = _WEEKDAY_ZH[disp.weekday()]
    header = f"📊 CoinMachine {disp.month}/{disp.day}({weekday}) 收盤"
    if data_date and disp != today:
        header += f"\n⚠️ 今日 {today.month}/{today.day} 資料尚未更新（以下為前一交易日）"

    # Quiet day: nothing in active categories → short message
    total_active = len(grouped["alert"]) + len(grouped["long"]) + len(grouped["short"])
    if total_active == 0:
        total_quiet = len(grouped["quiet"])
        return (
            f"{header}\n\n"
            f"🔍 今日 {total_quiet} 支股票皆無事件\n\n"
            f"詳情\n{WEBSITE_URL}\n"
        )

    lines: list[str] = [header, ""]
    state_stocks = state.get("stocks", {})

    for cat in ("alert", "long", "short"):
        stocks = grouped[cat]
        if not stocks:
            continue
        lines.append(f"━━━ {_CAT_HEADER[cat]} ({len(stocks)}) ━━━")
        lines.append("")
        dot = _CAT_DOT.get(cat, "")
        for s in stocks:
            sid = s["id"]
            name = watchlist_names.get(sid, "")
            chg = s.get("change_pct")
            chg_str = f"{chg:+.1f}%" if isinstance(chg, (int, float)) else ""
            line_header = f"{dot} {sid} {name}  {chg_str}".rstrip()
            lines.append(line_header)

            stock_counts = state_stocks.get(sid, {}).get("alerts", {})
            first = True
            for a in s["alerts"]:
                key = _normalize_alert_key(a)
                count = stock_counts.get(key, 1)
                label = _shorten_alert_for_display(a) + _consec_suffix(count)
                prefix = "   " if first else "   ・"
                lines.append(f"{prefix}{label}")
                first = False
            lines.append("")

    # Quiet stocks — compact, 2 per line
    quiet = grouped["quiet"]
    if quiet:
        lines.append(f"━━━ {_CAT_HEADER['quiet']} ({len(quiet)}) ━━━")
        entries = [f"{s['id']} {watchlist_names.get(s['id'], '')}".strip() for s in quiet]
        for i in range(0, len(entries), 2):
            lines.append("・".join(entries[i:i + 2]))
        lines.append("")

    lines.append("🔗 詳情")
    lines.append(WEBSITE_URL)
    # Compact trailing blank lines
    return "\n".join(lines).rstrip() + "\n"


# ---------- LINE push ----------

def _push(message: str, token: str, timeout: float = 10.0) -> bool:
    """POST broadcast to LINE. Returns True on HTTP 200, False otherwise.

    Network exceptions are caught and logged — caller treats False as 'skip'.
    """
    try:
        resp = requests.post(
            LINE_BROADCAST_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"messages": [{"type": "text", "text": message}]},
            timeout=timeout,
        )
    except requests.RequestException as e:
        log.error("LINE push HTTP error: %s", e)
        return False
    if resp.status_code != 200:
        log.error("LINE push failed %s: %s", resp.status_code, resp.text[:200])
        return False
    return True


# ---------- data ingestion ----------

def _build_today_dataset(
    watchlist_path: Path,
    stocks_dir: Path,
) -> tuple[dict[str, list[str]], dict[str, str], dict[str, dict]]:
    """Read watchlist + each stock's freshly-built JSON.

    Returns:
      today_alerts: {stock_id: [alert_text, ...]}  — empty list for stocks with no signals today
      watchlist_names: {stock_id: name}
      idx_map: {stock_id: {'close': float, 'change_pct': float_percent}}

    Skips inactive stocks entirely (not even in quiet list).
    """
    wl = json.loads(watchlist_path.read_text(encoding="utf-8"))

    today_alerts: dict[str, list[str]] = {}
    watchlist_names: dict[str, str] = {}
    idx_map: dict[str, dict] = {}

    for entry in wl.get("stocks", []):
        sid = entry["id"]
        watchlist_names[sid] = entry.get("name", sid)
        path = stocks_dir / f"{sid}.json"
        if not path.exists():
            today_alerts[sid] = []
            idx_map[sid] = {"close": None, "change_pct": None, "last_trade_date": None}
            continue
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            log.warning("load %s failed: %s", sid, e)
            today_alerts[sid] = []
            idx_map[sid] = {"close": None, "change_pct": None, "last_trade_date": None}
            continue
        if d.get("inactive"):
            continue  # skip inactive entirely
        latest = d.get("latest") or {}
        today_alerts[sid] = list(latest.get("alerts") or [])
        pv = latest.get("pv") or {}
        chg_frac = pv.get("price_change_pct")  # already a fraction like 0.041
        idx_map[sid] = {
            "close": latest.get("close"),
            "change_pct": (chg_frac * 100) if isinstance(chg_frac, (int, float)) else None,
            "last_trade_date": d.get("last_trade_date"),
        }

    return today_alerts, watchlist_names, idx_map


# ---------- main entry ----------

def send_daily_summary(
    watchlist_path: Path,
    stocks_dir: Path,
    state_path: Path,
    today: date | None = None,
    dry_run: bool = False,
    token: str | None = None,
) -> bool:
    """Main entry: read fresh data → compose message → push → save state.

    Returns True if pushed (or printed in dry-run mode), False on error /
    missing token.
    """
    today = today or date.today()
    token = token if token is not None else LINE_CHANNEL_ACCESS_TOKEN

    if not token and not dry_run:
        log.info("LINE_CHANNEL_ACCESS_TOKEN unset — skipping notify")
        return False

    today_alerts, names, idx_map = _build_today_dataset(watchlist_path, stocks_dir)

    grouped: dict[str, list[dict]] = {"alert": [], "long": [], "short": [], "quiet": []}
    for sid, alerts in today_alerts.items():
        cat = _categorize(alerts)
        grouped[cat].append({
            "id": sid,
            "alerts": alerts,
            "change_pct": idx_map.get(sid, {}).get("change_pct"),
        })

    today_iso = datetime.now(TAIPEI_TZ).isoformat(timespec="seconds")
    prev_state = _load_state(state_path)
    new_state = _update_state(
        prev_state,
        {sid: a for sid, a in today_alerts.items() if a},
        today_iso,
    )

    # Freshest trade date across active stocks → staleness annotation
    _trade_dates = [
        v.get("last_trade_date") for v in idx_map.values() if v.get("last_trade_date")
    ]
    data_date = max(_trade_dates) if _trade_dates else None

    msg = _format_message(grouped, new_state, names, today, data_date)

    if dry_run:
        print("=" * 60)
        print(msg)
        print("=" * 60)
        print(f"[length: {len(msg)} chars; alert={len(grouped['alert'])} "
              f"long={len(grouped['long'])} short={len(grouped['short'])} "
              f"quiet={len(grouped['quiet'])}]")
        return True

    # Safety: LINE text limit is 5000 chars
    if len(msg) > 4900:
        log.warning("message exceeds 4900 chars, truncating")
        msg = msg[:4800] + "\n...(訊息超長,請至網站查看完整資訊)"

    sent = _push(msg, token)
    if sent:
        _save_state(state_path, new_state)
        log.info("LINE pushed (%d chars)", len(msg))
    return sent


# ---------- CLI ----------

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from config import NOTIFY_STATE_FILE, STOCKS_DIR, WATCHLIST_FILE

    dry = "--dry-run" in sys.argv
    today_override: date | None = None
    for a in sys.argv[1:]:
        if a.startswith("--date="):
            today_override = date.fromisoformat(a.split("=", 1)[1])

    ok = send_daily_summary(
        WATCHLIST_FILE, STOCKS_DIR, NOTIFY_STATE_FILE,
        today=today_override,
        dry_run=dry,
    )
    sys.exit(0 if ok else 1)
