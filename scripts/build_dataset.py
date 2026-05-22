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
    RETRY_BACKOFF_SEC,
    RETRY_MAX_PASSES,
    RULE_VERSION,
    SCHEMA_VERSION,
    STOCKS_DIR,
    WARMUP_MONTHS,
    WATCHLIST_FILE,
)
from fetch_twse import Bar, FetchError, detect_market, fetch_history, fetch_month, fetch_twse_latest_all, is_twse_legacy_alive

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


def _merge_bars(existing: list[dict], fresh: list[Bar], prefer_existing: bool = False) -> list[dict]:
    """Merge fresh bars into existing. fresh wins by default; flip
    prefer_existing=True for retry passes that must not overwrite already-good
    data with a fallback source (e.g. snapshot)."""
    by_date: dict[str, dict] = {b["date"]: b for b in existing}
    for b in fresh:
        if prefer_existing and b.date in by_date:
            continue
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


def _pick_best_name(
    fresh: list[Bar], existing_json: dict | None, entry: dict, stock_id: str
) -> str:
    """Prefer fresh (just-fetched) name > existing JSON name > entry name > id.
    Skip any candidate that is empty or equal to the stock id (placeholder)."""
    fresh_name = next((b.name for b in fresh if b.name), "")
    existing_name = (existing_json or {}).get("name", "") or ""
    entry_name = entry.get("name", "") or ""
    for candidate in (fresh_name, existing_name, entry_name):
        if candidate and candidate != stock_id:
            return candidate
    return stock_id


def update_stock(
    entry: dict,
    twse_snapshot: dict[str, Bar] | None = None,
    use_twse_legacy: bool = False,
    force_full: bool = False,
    prefer_existing: bool = False,
) -> dict[str, Any]:
    """Update one stock; return result summary for meta tracking.

    TWSE flow has two modes (decided per-run by probing):
    - legacy alive → fetch_history with per-stock month endpoint (full backfill possible)
    - legacy dead  → fall back to twse_snapshot (latest trading day only)
    TPEx always uses per-stock month fetch (its endpoint is stable).
    """
    stock_id = entry["id"]
    market = entry.get("market")

    existing_history, existing_json = _existing_bars(stock_id)
    if force_full:
        existing_history = []

    if market is None:
        market = detect_market(stock_id)
        time.sleep(REQUEST_DELAY_SEC)

    fresh: list[Bar] = []
    if market == "TWSE":
        if use_twse_legacy:
            start = _start_date(existing_history)
            end = date.today()
            if start <= end:
                try:
                    fresh = fetch_history(stock_id, market, start, end)
                except FetchError:
                    fresh = []
        # Always also try snapshot in case legacy missed today or wasn't used.
        if twse_snapshot is None:
            twse_snapshot = fetch_twse_latest_all()
        bar = twse_snapshot.get(stock_id)
        if bar is not None:
            seen = {b.date for b in fresh} | {b["date"] for b in existing_history}
            if bar.date not in seen:
                fresh.append(bar)
    else:  # TPEx
        start = _start_date(existing_history)
        end = date.today()
        if start <= end:
            fresh = fetch_history(stock_id, market, start, end)

    resolved_name = _pick_best_name(fresh, existing_json, entry, stock_id)
    if resolved_name == stock_id and market is not None:
        # Fresh fetches got filtered out by date window (common when the stock
        # was added today and there's nothing new to merge). Do a cheap probe
        # on the current month just to harvest the company name. This adds one
        # API call only for stocks where we still don't know the name.
        today_d = date.today()
        try:
            probe_bars = fetch_month(stock_id, market, today_d.year, today_d.month)
            for b in probe_bars:
                if b.name:
                    resolved_name = b.name
                    break
        except Exception:  # noqa: BLE001  best-effort, name is non-critical
            log.warning("name probe failed for %s", stock_id)

    merged = _merge_bars(existing_history, fresh, prefer_existing=prefer_existing)
    df_full = _bars_to_df(merged)

    if df_full.empty:
        return {"id": stock_id, "status": "no_data", "market": market, "name": resolved_name}

    last_trade_date = df_full["date"].max()
    days_since = (date.today() - date.fromisoformat(last_trade_date)).days
    inactive = days_since >= INACTIVE_AFTER_MISSING_DAYS * 2

    from indicators import compute_indicators, detect_bb_divergence, detect_divergence, detect_rsi_divergence

    df_ind = compute_indicators(df_full)
    macd_divergence = detect_divergence(df_ind)
    rsi_divergence = detect_rsi_divergence(df_ind)
    bb_divergence = detect_bb_divergence(df_ind)
    result = analyze(df_ind, macd_divergence, rsi_divergence, bb_divergence)

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
        "rsi": {
            "value": _safe_float(today.get("rsi")),
            "zone": result["signals"].get("rsi_zone"),
            "numbing": result["signals"].get("rsi_numbing"),
            "divergence": result["signals"].get("rsi_divergence"),
            "strategy": result["signals"].get("rsi_strategy"),
        },
        "bb": {
            "upper": _safe_float(today.get("bb_upper")),
            "middle": _safe_float(today.get("bb_middle")),
            "lower": _safe_float(today.get("bb_lower")),
            "percent_b": _safe_float(today.get("percent_b")),
            "bandwidth": _safe_float(today.get("bandwidth")),
            "bandwidth_pct20": _safe_float(today.get("bandwidth_pct20")),
            "bandwidth_pct05": _safe_float(today.get("bandwidth_pct05")),
            "zone": result["signals"].get("bb_zone"),
            "cross": result["signals"].get("bb_cross"),
            "percent_b_zone": result["signals"].get("bb_percent_b_zone"),
            "bandwidth_state": result["signals"].get("bb_bandwidth_state"),
            "range_strategy": result["signals"].get("bb_range_strategy"),
            "divergence": result["signals"].get("bb_divergence"),
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
            "rsi": _safe_float(row.get("rsi")),
            "bb_upper": _safe_float(row.get("bb_upper")),
            "bb_middle": _safe_float(row.get("bb_middle")),
            "bb_lower": _safe_float(row.get("bb_lower")),
            "percent_b": _safe_float(row.get("percent_b")),
            "bandwidth": _safe_float(row.get("bandwidth")),
            "bandwidth_pct20": _safe_float(row.get("bandwidth_pct20")),
        }
        for _, row in df_keep.iterrows()
    ]

    payload = {
        "stock_id": stock_id,
        "name": resolved_name,
        "market": market,
        "last_updated": datetime.now(TAIPEI_TZ).isoformat(timespec="seconds"),
        "last_trade_date": last_trade_date,
        "rule_version": RULE_VERSION,
        "inactive": inactive,
        "latest": latest,
        "history": history,
    }

    _write_json(STOCKS_DIR / f"{stock_id}.json", payload)
    return {
        "id": stock_id,
        "status": "ok",
        "market": market,
        "name": resolved_name,
        "last_trade_date": last_trade_date,
    }


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


def _backfill_watchlist(watchlist: dict, results: list[dict]) -> bool:
    """Update watchlist entries with resolved name/market from results.

    Mutates `watchlist` in place. Returns True if anything changed (so caller
    knows to write it back). Skips entries with no matching result, and does
    not overwrite a real name with an id-as-placeholder.
    """
    by_id = {r["id"]: r for r in results}
    changed = False
    for entry in watchlist.get("stocks", []):
        r = by_id.get(entry["id"])
        if not r:
            continue
        new_name = r.get("name")
        new_market = r.get("market")
        if new_name and new_name != entry["id"] and new_name != entry.get("name"):
            entry["name"] = new_name
            changed = True
        if new_market and new_market != entry.get("market"):
            entry["market"] = new_market
            changed = True
    return changed


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


def _run_one_pass(
    entries: list[dict],
    twse_snapshot: dict[str, Bar],
    use_twse_legacy: bool,
    prefer_existing: bool = False,
) -> tuple[list[dict], list[dict]]:
    """Single sweep through entries. Returns (results, failures)."""
    results: list[dict] = []
    failures: list[dict] = []
    for i, entry in enumerate(entries):
        sid = entry["id"]
        if i > 0:
            # Sleep before any month-endpoint fetch (TPEx always, TWSE only if legacy alive)
            if entry.get("market") != "TWSE" or use_twse_legacy:
                time.sleep(REQUEST_DELAY_SEC)
        try:
            r = update_stock(
                entry,
                twse_snapshot=twse_snapshot,
                use_twse_legacy=use_twse_legacy,
                prefer_existing=prefer_existing,
            )
            log.info("ok %s %s (%s)", sid, r.get("market"), r.get("last_trade_date"))
            results.append(r)
        except FetchError as e:
            log.error("fetch failed %s: %s", sid, e)
            failures.append({"id": sid, "reason": str(e), "type": "fetch"})
        except Exception as e:  # noqa: BLE001
            log.error("unexpected failure %s: %s\n%s", sid, e, traceback.format_exc())
            failures.append({"id": sid, "reason": str(e), "type": "exception"})
    return results, failures


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

    has_twse = any(e.get("market") == "TWSE" or e.get("market") is None for e in entries)
    use_twse_legacy = False
    twse_snapshot: dict[str, Bar] = {}
    if has_twse:
        use_twse_legacy = is_twse_legacy_alive()
        log.info("TWSE legacy endpoint: %s", "alive (per-stock month fetch)" if use_twse_legacy else "dead (snapshot fallback)")
        try:
            twse_snapshot = fetch_twse_latest_all()
            log.info("twse snapshot: %d stocks for latest trading day", len(twse_snapshot))
        except Exception as e:  # noqa: BLE001
            log.error("twse snapshot failed: %s", e)

    results, failures = _run_one_pass(entries, twse_snapshot, use_twse_legacy, prefer_existing=False)
    retry_attempts: dict[str, int] = {f["id"]: 0 for f in failures}

    for attempt in range(1, RETRY_MAX_PASSES + 1):
        if not failures:
            break
        log.info("retry pass %d: %d stocks (backing off %ds)", attempt, len(failures), RETRY_BACKOFF_SEC)
        time.sleep(RETRY_BACKOFF_SEC)

        # Refresh snapshot if first attempt failed entirely (still empty)
        if has_twse and not twse_snapshot:
            try:
                twse_snapshot = fetch_twse_latest_all()
                log.info("twse snapshot refresh: %d stocks", len(twse_snapshot))
            except Exception as e:  # noqa: BLE001
                log.error("twse snapshot refresh failed: %s", e)

        retry_ids = {f["id"] for f in failures}
        retry_entries = [e for e in entries if e["id"] in retry_ids]
        retry_results, retry_failures = _run_one_pass(
            retry_entries, twse_snapshot, use_twse_legacy, prefer_existing=True,
        )
        succeeded_ids = {r["id"] for r in retry_results if r.get("status") in ("ok", "no_data")}
        results.extend(r for r in retry_results if r["id"] in succeeded_ids)
        failures = retry_failures
        for fid in {f["id"] for f in failures}:
            retry_attempts[fid] = attempt

    for f in failures:
        f["retry_attempts"] = retry_attempts.get(f["id"], 0)

    if _backfill_watchlist(watchlist, results):
        _write_json(WATCHLIST_FILE, watchlist)
        log.info("watchlist backfilled (name/market)")

    _write_index(watchlist, results)
    _write_meta(time.time() - started, results, failures)
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
