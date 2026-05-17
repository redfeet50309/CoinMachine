"""Main orchestrator: read watchlist → fetch OHLCV → compute → analyze → write JSON.

Usage:
    python build_dataset.py            # update all watchlist stocks
    python build_dataset.py 2330 8299  # update specific stocks only
"""

from __future__ import annotations

import json
import logging
import sys
import time
import traceback
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd
from dateutil.relativedelta import relativedelta

from analyze import analyze
from config import (
    HISTORY_KEEP_DAYS,
    INACTIVE_AFTER_MISSING_DAYS,
    INDEX_FILE,
    META_FILE,
    REQUEST_DELAY_SEC,
    RULE_VERSION,
    SCHEMA_VERSION,
    STOCKS_DIR,
    WARMUP_MONTHS,
    WATCHLIST_FILE,
)
from fetch_twse import Bar, FetchError, detect_market, fetch_history, fetch_twse_latest_all

log = logging.getLogger(__name__)
TAIPEI_TZ = timezone(timedelta(hours=8))


def _read_json(path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_watchlist() -> dict:
    wl = _read_json(WATCHLIST_FILE)
    if wl is None:
        raise FileNotFoundError(f"watchlist not found: {WATCHLIST_FILE}")
    return wl


def _existing_bars(stock_id: str) -> tuple[list[dict], dict | None]:
    """Return (history bars, existing full JSON) — empty list if no file."""
    path = STOCKS_DIR / f"{stock_id}.json"
    existing = _read_json(path)
    if existing is None:
        return [], None
    return existing.get("history") or [], existing


def _bars_to_df(bars: list[dict]) -> pd.DataFrame:
    if not bars:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(bars)
    df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
    return df[["date", "open", "high", "low", "close", "volume"]].sort_values("date").reset_index(drop=True)


def _merge_bars(existing: list[dict], fresh: list[Bar]) -> list[dict]:
    by_date: dict[str, dict] = {b["date"]: b for b in existing}
    for b in fresh:
        by_date[b.date] = {
            "date": b.date, "o": b.open, "h": b.high, "l": b.low, "c": b.close, "v": b.volume
        }
    return sorted(by_date.values(), key=lambda x: x["date"])


def _start_date(existing: list[dict]) -> date:
    """If we already have data, start at last_date + 1 day, else WARMUP_MONTHS back."""
    if existing:
        last = max(b["date"] for b in existing)
        return date.fromisoformat(last) + timedelta(days=1)
    today = date.today()
    return (today - relativedelta(months=WARMUP_MONTHS)).replace(day=1)


def update_stock(
    entry: dict,
    twse_snapshot: dict[str, Bar] | None = None,
    force_full: bool = False,
) -> dict[str, Any]:
    """Update one stock; return result summary for meta tracking.

    For TWSE stocks we use the bulk OpenAPI snapshot (twse_snapshot) which
    contains the latest trading day for every listed stock — the legacy
    /exchangeReport/STOCK_DAY endpoint started returning 404 in 2026-05 and
    OpenAPI is the only working source. TPEx still uses per-stock month fetch.
    """
    stock_id = entry["id"]
    name = entry.get("name", stock_id)
    market = entry.get("market")

    existing_history, existing_json = _existing_bars(stock_id)
    if force_full:
        existing_history = []

    if market is None:
        market = detect_market(stock_id)
        time.sleep(REQUEST_DELAY_SEC)

    fresh: list[Bar] = []
    if market == "TWSE":
        # OpenAPI provides only the most recent trading day per stock.
        # Backfill of older days is no longer possible via TWSE — existing
        # history files carry the warmup data.
        if twse_snapshot is None:
            twse_snapshot = fetch_twse_latest_all()
        bar = twse_snapshot.get(stock_id)
        if bar is not None:
            existing_dates = {b["date"] for b in existing_history}
            if bar.date not in existing_dates:
                fresh = [bar]
    else:  # TPEx
        start = _start_date(existing_history)
        end = date.today()
        if start <= end:
            fresh = fetch_history(stock_id, market, start, end)

    merged = _merge_bars(existing_history, fresh)
    df_full = _bars_to_df(merged)

    if df_full.empty:
        return {"id": stock_id, "status": "no_data", "market": market}

    last_trade_date = df_full["date"].max()
    days_since = (date.today() - date.fromisoformat(last_trade_date)).days
    inactive = days_since >= INACTIVE_AFTER_MISSING_DAYS * 2

    from indicators import compute_indicators, detect_divergence

    df_ind = compute_indicators(df_full)
    divergence = detect_divergence(df_ind)
    result = analyze(df_ind, divergence)

    today = df_ind.iloc[-1]
    latest = {
        "close": _safe_float(today.get("close")),
        "volume": _safe_int(today.get("volume")),
        "ma": {f"ma{p}": _safe_float(today.get(f"ma{p}")) for p in (5, 10, 20, 60, 120, 240)},
        "macd": {
            "dif": _safe_float(today.get("dif")),
            "macd": _safe_float(today.get("macd")),
            "osc": _safe_float(today.get("osc")),
        },
        "signals": result["signals"],
        "alerts": result["alerts"],
    }

    df_keep = df_ind.tail(HISTORY_KEEP_DAYS).copy()
    history = [
        {
            "date": row["date"],
            "o": _safe_float(row["open"]),
            "h": _safe_float(row["high"]),
            "l": _safe_float(row["low"]),
            "c": _safe_float(row["close"]),
            "v": _safe_int(row["volume"]),
            "ma5": _safe_float(row.get("ma5")),
            "ma20": _safe_float(row.get("ma20")),
            "ma60": _safe_float(row.get("ma60")),
            "dif": _safe_float(row.get("dif")),
            "macd": _safe_float(row.get("macd")),
            "osc": _safe_float(row.get("osc")),
        }
        for _, row in df_keep.iterrows()
    ]

    payload = {
        "stock_id": stock_id,
        "name": name,
        "market": market,
        "last_updated": datetime.now(TAIPEI_TZ).isoformat(timespec="seconds"),
        "last_trade_date": last_trade_date,
        "rule_version": RULE_VERSION,
        "inactive": inactive,
        "latest": latest,
        "history": history,
    }

    _write_json(STOCKS_DIR / f"{stock_id}.json", payload)
    return {"id": stock_id, "status": "ok", "market": market, "last_trade_date": last_trade_date}


def _safe_float(v) -> float | None:
    if v is None:
        return None
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return None
    if pd.isna(fv):
        return None
    return round(fv, 4)


def _safe_int(v) -> int | None:
    if v is None:
        return None
    try:
        iv = int(float(v))
    except (TypeError, ValueError):
        return None
    return iv


def _write_index(watchlist: dict, results: list[dict]) -> None:
    by_id = {r["id"]: r for r in results}
    stocks = []
    for entry in watchlist.get("stocks", []):
        sid = entry["id"]
        r = by_id.get(sid, {})
        stocks.append(
            {
                "id": sid,
                "name": entry.get("name", sid),
                "market": r.get("market") or entry.get("market"),
                "updated": r.get("last_trade_date"),
                "status": r.get("status", "unknown"),
            }
        )
    _write_json(
        INDEX_FILE,
        {
            "generated_at": datetime.now(TAIPEI_TZ).isoformat(timespec="seconds"),
            "schema_version": SCHEMA_VERSION,
            "stocks": stocks,
        },
    )


def _write_meta(duration: float, results: list[dict], failures: list[dict]) -> None:
    _write_json(
        META_FILE,
        {
            "last_run": datetime.now(TAIPEI_TZ).isoformat(timespec="seconds"),
            "duration_seconds": round(duration, 1),
            "stocks_processed": len(results),
            "failures": failures,
            "rule_version": RULE_VERSION,
            "schema_version": SCHEMA_VERSION,
        },
    )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    argv = argv or sys.argv[1:]

    watchlist = _load_watchlist()
    entries = watchlist.get("stocks", [])
    if argv:
        wanted = set(argv)
        entries = [e for e in entries if e["id"] in wanted]

    if not entries:
        log.warning("nothing to do")
        return 0

    started = time.time()
    results: list[dict] = []
    failures: list[dict] = []

    # One-shot bulk fetch for all TWSE stocks (only endpoint that still works
    # since 2026-05). TPEx stocks fall through to per-stock month fetch below.
    twse_snapshot: dict[str, Bar] = {}
    if any(e.get("market") == "TWSE" or e.get("market") is None for e in entries):
        try:
            twse_snapshot = fetch_twse_latest_all()
            log.info("twse snapshot: %d stocks for latest trading day", len(twse_snapshot))
        except Exception as e:  # noqa: BLE001
            log.error("twse snapshot failed: %s", e)

    for i, entry in enumerate(entries):
        sid = entry["id"]
        if i > 0 and entry.get("market") != "TWSE":
            time.sleep(REQUEST_DELAY_SEC)
        try:
            r = update_stock(entry, twse_snapshot=twse_snapshot)
            log.info("ok %s %s (%s)", sid, r.get("market"), r.get("last_trade_date"))
            results.append(r)
        except FetchError as e:
            log.error("fetch failed %s: %s", sid, e)
            failures.append({"id": sid, "reason": str(e), "type": "fetch"})
        except Exception as e:  # noqa: BLE001
            log.error("unexpected failure %s: %s\n%s", sid, e, traceback.format_exc())
            failures.append({"id": sid, "reason": str(e), "type": "exception"})

    _write_index(watchlist, results)
    _write_meta(time.time() - started, results, failures)
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
