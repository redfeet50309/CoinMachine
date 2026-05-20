"""Tests for pure helpers inside build_dataset.py.

retry-loop integration (Part 4 plan) lives further down in this file and will
be expanded once _run_one_pass / RETRY_MAX_PASSES land.
"""

import math
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest
from dateutil.relativedelta import relativedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from build_dataset import (  # noqa: E402
    _bars_to_df,
    _merge_bars,
    _safe_float,
    _safe_int,
    _start_date,
)
from fetch_twse import Bar  # noqa: E402


# ---------- _safe_float ----------

def test_safe_float_none():
    assert _safe_float(None) is None


def test_safe_float_nan():
    assert _safe_float(float("nan")) is None


def test_safe_float_pandas_na():
    assert _safe_float(pd.NA) is None


def test_safe_float_rounds_to_4_decimals():
    assert _safe_float(1.234567) == 1.2346


def test_safe_float_string_numeric():
    assert _safe_float("3.5") == 3.5


def test_safe_float_invalid_string():
    assert _safe_float("not-a-number") is None


# ---------- _safe_int ----------

def test_safe_int_none():
    assert _safe_int(None) is None


def test_safe_int_truncates_float():
    assert _safe_int(123.7) == 123


def test_safe_int_string_decimal():
    assert _safe_int("123.0") == 123


def test_safe_int_invalid_returns_none():
    assert _safe_int("oops") is None


# ---------- _bars_to_df ----------

def test_bars_to_df_empty_input():
    df = _bars_to_df([])
    assert list(df.columns) == ["date", "open", "high", "low", "close", "volume"]
    assert len(df) == 0


def test_bars_to_df_renames_short_keys():
    bars = [
        {"date": "2026-03-02", "o": 10, "h": 12, "l": 9, "c": 11, "v": 1000},
        {"date": "2026-03-01", "o": 9, "h": 11, "l": 8, "c": 10, "v": 800},
    ]
    df = _bars_to_df(bars)
    # Sorted by date
    assert df.iloc[0]["date"] == "2026-03-01"
    assert df.iloc[1]["close"] == 11
    assert df.iloc[0]["volume"] == 800


# ---------- _merge_bars ----------

def _b(d, c=100.0):
    return Bar(date=d, open=c, high=c, low=c, close=c, volume=1000)


def test_merge_bars_dedupe_by_date():
    existing = [{"date": "2026-03-01", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}]
    fresh = [_b("2026-03-02")]
    out = _merge_bars(existing, fresh)
    assert [b["date"] for b in out] == ["2026-03-01", "2026-03-02"]


def test_merge_bars_fresh_overwrites_existing_same_date():
    # Current default behavior: fresh wins. Part 4 will add prefer_existing
    # to flip this for retry passes.
    existing = [{"date": "2026-03-02", "o": 1, "h": 1, "l": 1, "c": 50, "v": 100}]
    fresh = [_b("2026-03-02", c=99.9)]
    out = _merge_bars(existing, fresh)
    assert len(out) == 1
    assert out[0]["c"] == 99.9


def test_merge_bars_keeps_sort_order():
    existing = [
        {"date": "2026-03-03", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1},
        {"date": "2026-03-01", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1},
    ]
    fresh = [_b("2026-03-02")]
    out = _merge_bars(existing, fresh)
    assert [b["date"] for b in out] == ["2026-03-01", "2026-03-02", "2026-03-03"]


def test_merge_bars_empty_existing():
    fresh = [_b("2026-03-01"), _b("2026-03-02")]
    out = _merge_bars([], fresh)
    assert [b["date"] for b in out] == ["2026-03-01", "2026-03-02"]


def test_merge_bars_empty_fresh_returns_existing():
    existing = [
        {"date": "2026-03-01", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1},
    ]
    out = _merge_bars(existing, [])
    assert out == existing


def test_merge_bars_prefer_existing_skips_same_date():
    existing = [{"date": "2026-03-02", "o": 1, "h": 1, "l": 1, "c": 50, "v": 100}]
    fresh = [_b("2026-03-02", c=99.9)]
    out = _merge_bars(existing, fresh, prefer_existing=True)
    assert len(out) == 1
    # existing wins → close stays 50
    assert out[0]["c"] == 50


def test_merge_bars_prefer_existing_still_adds_new_dates():
    existing = [{"date": "2026-03-02", "o": 1, "h": 1, "l": 1, "c": 50, "v": 100}]
    fresh = [_b("2026-03-02", c=99.9), _b("2026-03-03", c=60)]
    out = _merge_bars(existing, fresh, prefer_existing=True)
    assert [b["date"] for b in out] == ["2026-03-02", "2026-03-03"]
    # 2026-03-02 kept existing close=50, 2026-03-03 added with close=60
    assert out[0]["c"] == 50
    assert out[1]["c"] == 60


# ---------- _start_date ----------

def test_start_date_empty_history_uses_warmup_window():
    from config import WARMUP_MONTHS
    today = date.today()
    expected = (today - relativedelta(months=WARMUP_MONTHS)).replace(day=1)
    assert _start_date([]) == expected


def test_start_date_from_existing_uses_last_plus_one_day():
    existing = [
        {"date": "2026-03-01"},
        {"date": "2026-04-15"},
        {"date": "2026-04-10"},
    ]
    # last = 2026-04-15 → expected = 2026-04-16
    assert _start_date(existing) == date(2026, 4, 16)


# ---------- _run_one_pass / retry loop (integration via monkeypatch) ----------

def test_run_one_pass_collects_results_and_failures(monkeypatch):
    import build_dataset
    from fetch_twse import FetchError

    call_count = {"n": 0}

    def fake_update(entry, **kwargs):
        call_count["n"] += 1
        if entry["id"] == "FAIL":
            raise FetchError("simulated fetch fail")
        return {"id": entry["id"], "status": "ok", "market": "TWSE",
                "last_trade_date": "2026-05-19"}

    monkeypatch.setattr(build_dataset, "update_stock", fake_update)
    monkeypatch.setattr(build_dataset, "time", type("T", (), {"sleep": lambda *a: None}))

    entries = [{"id": "OK1", "market": "TPEx"}, {"id": "FAIL", "market": "TPEx"}]
    results, failures = build_dataset._run_one_pass(entries, {}, False)
    assert [r["id"] for r in results] == ["OK1"]
    assert [f["id"] for f in failures] == ["FAIL"]
    assert failures[0]["type"] == "fetch"
    assert call_count["n"] == 2


def test_run_one_pass_passes_prefer_existing_through(monkeypatch):
    import build_dataset
    received = {}

    def fake_update(entry, **kwargs):
        received["prefer_existing"] = kwargs.get("prefer_existing", False)
        return {"id": entry["id"], "status": "ok", "market": "TWSE",
                "last_trade_date": "2026-05-19"}

    monkeypatch.setattr(build_dataset, "update_stock", fake_update)
    monkeypatch.setattr(build_dataset, "time", type("T", (), {"sleep": lambda *a: None}))

    build_dataset._run_one_pass([{"id": "X", "market": "TPEx"}], {}, False, prefer_existing=True)
    assert received["prefer_existing"] is True
