"""Fetch OHLCV from TWSE (上市) and TPEx (上櫃).

Both endpoints return data one month at a time per stock. Output normalized
to: date (YYYY-MM-DD), open, high, low, close, volume (shares).

TWSE response:
  {"stat":"OK","date":"...","fields":[...],
   "data":[["115/03/02","57,404,594",amount,"o","h","l","c","change",trades,note]]}

TPEx response:
  {"tables":[{"fields":[...],
              "data":[["115/03/02","成交張數","成交仟元","o","h","l","c","change","筆數"]]}],
   "stat":"OK"}
  - 成交張數 × 1000 = 股
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable, Literal

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config import (
    REQUEST_DELAY_SEC,
    RETRY_ATTEMPTS,
    RETRY_MAX_WAIT,
    RETRY_MIN_WAIT,
    TPEX_ENDPOINT,
    TWSE_ENDPOINT,
    TWSE_OPENAPI_STOCK_DAY_ALL,
    USER_AGENT,
)

log = logging.getLogger(__name__)

Market = Literal["TWSE", "TPEx"]


@dataclass
class Bar:
    date: str        # ISO YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float
    volume: int      # shares


class FetchError(Exception):
    """Permanent failure (not retryable)."""


class TransientError(Exception):
    """Retryable network/API issue."""


_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})


def _roc_to_iso(roc: str) -> str:
    """'115/03/02' -> '2026-03-02'."""
    y, m, d = roc.strip().split("/")
    return f"{int(y) + 1911:04d}-{int(m):02d}-{int(d):02d}"


def _to_float(s: str) -> float:
    s = s.replace(",", "").strip()
    if s in ("", "--", "X"):
        return float("nan")
    # TWSE change column may carry leading +/-/X
    if s.startswith(("+", "X")):
        s = s.lstrip("+X")
    return float(s)


def _to_int(s: str) -> int:
    s = s.replace(",", "").strip()
    if s in ("", "--"):
        return 0
    return int(float(s))


@retry(
    reraise=True,
    stop=stop_after_attempt(RETRY_ATTEMPTS),
    wait=wait_exponential(multiplier=1, min=RETRY_MIN_WAIT, max=RETRY_MAX_WAIT),
    retry=retry_if_exception_type(TransientError),
)
def _get_json(url: str, params: dict) -> dict:
    try:
        r = _session.get(url, params=params, timeout=20)
    except requests.RequestException as e:
        raise TransientError(str(e)) from e
    if r.status_code in (429, 500, 502, 503, 504):
        raise TransientError(f"HTTP {r.status_code}")
    if r.status_code != 200:
        raise FetchError(f"HTTP {r.status_code}: {r.text[:200]}")
    try:
        return r.json()
    except ValueError as e:
        raise TransientError(f"Bad JSON: {e}") from e


def _parse_twse(payload: dict) -> list[Bar]:
    if (payload.get("stat") or "").upper() != "OK":
        return []
    rows = payload.get("data") or []
    bars: list[Bar] = []
    for r in rows:
        try:
            bars.append(
                Bar(
                    date=_roc_to_iso(r[0]),
                    volume=_to_int(r[1]),
                    open=_to_float(r[3]),
                    high=_to_float(r[4]),
                    low=_to_float(r[5]),
                    close=_to_float(r[6]),
                )
            )
        except (IndexError, ValueError) as e:
            log.warning("twse parse row failed: %s (%s)", r, e)
    return bars


def _parse_tpex(payload: dict) -> list[Bar]:
    stat = (payload.get("stat") or "").upper()
    if stat and stat != "OK":
        return []
    tables = payload.get("tables") or []
    if not tables:
        return []
    rows = tables[0].get("data") or []
    bars: list[Bar] = []
    for r in rows:
        try:
            bars.append(
                Bar(
                    date=_roc_to_iso(r[0]),
                    # TPEx 成交張數 × 1000 = 股
                    volume=_to_int(r[1]) * 1000,
                    open=_to_float(r[3]),
                    high=_to_float(r[4]),
                    low=_to_float(r[5]),
                    close=_to_float(r[6]),
                )
            )
        except (IndexError, ValueError) as e:
            log.warning("tpex parse row failed: %s (%s)", r, e)
    return bars


def is_twse_legacy_alive() -> bool:
    """Probe whether /exchangeReport/STOCK_DAY is currently serving real data.

    The legacy per-stock month endpoint started returning 404 from HiNetCDN
    on 2026-05-17 morning, then recovered later the same day. Status flips
    are not announced, so we probe each run.
    """
    try:
        bars = fetch_month("2330", "TWSE", 2026, 3)
        return len(bars) > 0
    except Exception:
        return False


def fetch_twse_latest_all() -> dict[str, Bar]:
    """One-shot snapshot of the latest trading day for every TWSE-listed stock.

    Uses the official OpenAPI endpoint, which is the only TWSE source still
    serving daily OHLCV reliably (the legacy /exchangeReport/STOCK_DAY started
    returning 404 from HiNetCDN in mid-2026). Returns dict keyed by stock id.
    """
    payload = _get_json(TWSE_OPENAPI_STOCK_DAY_ALL, {})
    if not isinstance(payload, list):
        return {}
    out: dict[str, Bar] = {}
    for row in payload:
        try:
            code = row.get("Code")
            roc_date = row.get("Date")  # "1150515" = 2026/05/15
            if not code or not roc_date or len(roc_date) < 7:
                continue
            iso_date = f"{int(roc_date[:-4]) + 1911:04d}-{roc_date[-4:-2]}-{roc_date[-2:]}"
            out[code] = Bar(
                date=iso_date,
                open=_to_float(row.get("OpeningPrice", "")),
                high=_to_float(row.get("HighestPrice", "")),
                low=_to_float(row.get("LowestPrice", "")),
                close=_to_float(row.get("ClosingPrice", "")),
                volume=_to_int(row.get("TradeVolume", "0")),
            )
        except (ValueError, TypeError, KeyError) as e:
            log.warning("twse openapi row parse failed: %s (%s)", row, e)
    return out


def fetch_month(stock_id: str, market: Market, year: int, month: int) -> list[Bar]:
    """Fetch a single month of daily bars for one stock."""
    if market == "TWSE":
        params = {
            "response": "json",
            "date": f"{year:04d}{month:02d}01",
            "stockNo": stock_id,
        }
        payload = _get_json(TWSE_ENDPOINT, params)
        return _parse_twse(payload)
    if market == "TPEx":
        params = {
            "code": stock_id,
            "date": f"{year:04d}/{month:02d}/01",
            "id": "",
            "response": "json",
        }
        payload = _get_json(TPEX_ENDPOINT, params)
        return _parse_tpex(payload)
    raise ValueError(f"unknown market: {market}")


def detect_market(stock_id: str, probe_date: date | None = None) -> Market:
    """Probe TWSE first; if empty, return TPEx. Caller should cache the result."""
    d = probe_date or _recent_trading_date()
    twse = fetch_month(stock_id, "TWSE", d.year, d.month)
    if twse:
        return "TWSE"
    time.sleep(REQUEST_DELAY_SEC)
    tpex = fetch_month(stock_id, "TPEx", d.year, d.month)
    if tpex:
        return "TPEx"
    raise FetchError(f"stock {stock_id} not found on TWSE or TPEx")


def _recent_trading_date() -> date:
    """Return today, or previous Friday if weekend."""
    d = date.today()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def months_between(start: date, end: date) -> list[tuple[int, int]]:
    """Inclusive list of (year, month) tuples."""
    out: list[tuple[int, int]] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append((y, m))
        m += 1
        if m == 13:
            m = 1
            y += 1
    return out


def fetch_history(
    stock_id: str,
    market: Market,
    start: date,
    end: date,
    delay: float = REQUEST_DELAY_SEC,
) -> list[Bar]:
    """Fetch all bars between start and end (inclusive), month by month."""
    all_bars: list[Bar] = []
    seen_dates: set[str] = set()
    months = months_between(start, end)
    for i, (y, m) in enumerate(months):
        if i > 0:
            time.sleep(delay)
        bars = fetch_month(stock_id, market, y, m)
        for b in bars:
            if start.isoformat() <= b.date <= end.isoformat() and b.date not in seen_dates:
                all_bars.append(b)
                seen_dates.add(b.date)
    all_bars.sort(key=lambda x: x.date)
    return all_bars


def bars_to_records(bars: Iterable[Bar]) -> list[dict]:
    return [
        {"date": b.date, "o": b.open, "h": b.high, "l": b.low, "c": b.close, "v": b.volume}
        for b in bars
    ]
