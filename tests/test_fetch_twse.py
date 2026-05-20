"""Parser-level tests for fetch_twse.py.

Pure-function tests — no network. Fixture payloads mirror the real shape of
TWSE / TPEx / OpenAPI responses.
"""

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from fetch_twse import (  # noqa: E402
    Bar,
    _parse_tpex,
    _parse_twse,
    _roc_to_iso,
    _to_float,
    _to_int,
    fetch_twse_latest_all,
    months_between,
)


# ---------- _roc_to_iso ----------

def test_roc_to_iso_basic():
    assert _roc_to_iso("115/03/02") == "2026-03-02"


def test_roc_to_iso_zero_padded():
    assert _roc_to_iso("100/01/01") == "2011-01-01"


def test_roc_to_iso_strips_whitespace():
    assert _roc_to_iso("  115/12/31  ") == "2026-12-31"


# ---------- _to_float ----------

def test_to_float_with_comma():
    assert _to_float("1,234.5") == 1234.5


def test_to_float_dashdash_is_nan():
    import math
    assert math.isnan(_to_float("--"))


def test_to_float_empty_is_nan():
    import math
    assert math.isnan(_to_float(""))


def test_to_float_plus_sign_stripped():
    assert _to_float("+5.5") == 5.5


def test_to_float_x_marker_stripped():
    # TWSE change column may carry 'X' marker
    assert _to_float("X3.2") == 3.2


def test_to_float_x_alone_is_nan():
    import math
    assert math.isnan(_to_float("X"))


def test_to_float_negative_passes_through():
    assert _to_float("-1.25") == -1.25


# ---------- _to_int ----------

def test_to_int_with_comma():
    assert _to_int("1,000,000") == 1_000_000


def test_to_int_empty_is_zero():
    assert _to_int("") == 0


def test_to_int_dashdash_is_zero():
    assert _to_int("--") == 0


def test_to_int_handles_decimal_form():
    # TPEx volume sometimes formatted as "1234.0"
    assert _to_int("1234.0") == 1234


# ---------- _parse_twse ----------

def test_parse_twse_ok_basic():
    payload = {
        "stat": "OK",
        "data": [
            # date, vol, amount, open, high, low, close, change, trades, note
            ["115/03/02", "57,404,594", "1,234,567,890",
             "910.00", "920.00", "905.00", "915.00", "+5.00", "30,000", ""],
        ],
    }
    bars = _parse_twse(payload)
    assert len(bars) == 1
    assert bars[0] == Bar(
        date="2026-03-02",
        open=910.0, high=920.0, low=905.0, close=915.0,
        volume=57_404_594,
    )


def test_parse_twse_stat_not_ok_returns_empty():
    payload = {"stat": "很抱歉，沒有符合條件的資料", "data": [["115/03/02"]]}
    assert _parse_twse(payload) == []


def test_parse_twse_stat_missing_returns_empty():
    assert _parse_twse({"data": []}) == []


def test_parse_twse_skips_malformed_row():
    payload = {
        "stat": "OK",
        "data": [
            ["115/03/02"],  # truncated — IndexError, should be skipped
            ["115/03/03", "1,000", "1,000",
             "10", "12", "9", "11", "+1", "5", ""],
        ],
    }
    bars = _parse_twse(payload)
    assert len(bars) == 1
    assert bars[0].date == "2026-03-03"


def test_parse_twse_dashdash_in_price_yields_nan():
    import math
    payload = {
        "stat": "OK",
        "data": [
            ["115/03/02", "1,000", "1,000",
             "--", "--", "--", "--", "", "0", ""],
        ],
    }
    bars = _parse_twse(payload)
    assert len(bars) == 1
    assert math.isnan(bars[0].open)
    assert math.isnan(bars[0].close)


# ---------- _parse_tpex ----------

def test_parse_tpex_ok_basic():
    payload = {
        "tables": [{
            "data": [
                # date, 成交張數, 成交仟元, open, high, low, close, change, 筆數
                ["115/03/02", "9,028", "100,000",
                 "2,450.00", "2,470.00", "2,440.00", "2,465.00", "+15.00", "100"],
            ],
        }],
        "stat": "OK",
    }
    bars = _parse_tpex(payload)
    assert len(bars) == 1
    # TPEx 成交張數 × 1000 = 股 → 9,028 * 1000
    assert bars[0].volume == 9_028_000
    assert bars[0].open == 2450.0
    assert bars[0].close == 2465.0
    assert bars[0].date == "2026-03-02"


def test_parse_tpex_no_tables_returns_empty():
    assert _parse_tpex({"tables": [], "stat": "OK"}) == []


def test_parse_tpex_missing_tables_key():
    assert _parse_tpex({"stat": "OK"}) == []


def test_parse_tpex_stat_not_ok_returns_empty():
    payload = {
        "tables": [{"data": [["115/03/02", "1", "1", "1", "1", "1", "1", "+0", "0"]]}],
        "stat": "ERROR",
    }
    assert _parse_tpex(payload) == []


def test_parse_tpex_skips_malformed_row():
    payload = {
        "tables": [{
            "data": [
                ["bad-row-no-fields"],
                ["115/03/02", "100", "1000",
                 "10", "12", "9", "11", "+1", "5"],
            ],
        }],
        "stat": "OK",
    }
    bars = _parse_tpex(payload)
    assert len(bars) == 1
    assert bars[0].volume == 100_000  # 100 lots × 1000


def test_parse_tpex_stat_field_absent_is_ok():
    # If stat field is missing entirely, _parse_tpex treats it as OK
    payload = {
        "tables": [{
            "data": [["115/03/02", "1", "1", "1", "1", "1", "1", "+0", "0"]],
        }],
    }
    bars = _parse_tpex(payload)
    assert len(bars) == 1


# ---------- fetch_twse_latest_all (parser only; we patch the GET) ----------

def test_fetch_twse_latest_all_parses_list(monkeypatch):
    sample = [
        {
            "Code": "2330",
            "Date": "1150515",  # ROC year 115 → 2026, month 05, day 15
            "OpeningPrice": "900.00",
            "HighestPrice": "910.00",
            "LowestPrice": "895.00",
            "ClosingPrice": "905.00",
            "TradeVolume": "30,000,000",
        },
        {
            "Code": "8299",
            "Date": "1150515",
            "OpeningPrice": "2,400.00",
            "HighestPrice": "2,470.00",
            "LowestPrice": "2,390.00",
            "ClosingPrice": "2,465.00",
            "TradeVolume": "9,028,000",
        },
    ]
    import fetch_twse
    monkeypatch.setattr(fetch_twse, "_get_json", lambda url, params: sample)
    out = fetch_twse_latest_all()
    assert set(out.keys()) == {"2330", "8299"}
    assert out["2330"].date == "2026-05-15"
    assert out["2330"].close == 905.0
    assert out["8299"].volume == 9_028_000


def test_fetch_twse_latest_all_skips_missing_code():
    import fetch_twse
    sample = [
        {"Date": "1150515", "ClosingPrice": "100"},  # no Code
        {"Code": "0050", "Date": "115", "ClosingPrice": "100"},  # bad date length
    ]
    orig = fetch_twse._get_json
    fetch_twse._get_json = lambda url, params: sample  # noqa: SLF001
    try:
        out = fetch_twse_latest_all()
        assert out == {}
    finally:
        fetch_twse._get_json = orig


def test_fetch_twse_latest_all_non_list_payload(monkeypatch):
    import fetch_twse
    monkeypatch.setattr(fetch_twse, "_get_json", lambda url, params: {"oops": "wrong shape"})
    assert fetch_twse_latest_all() == {}


# ---------- months_between ----------

def test_months_between_inclusive_basic():
    out = months_between(date(2026, 1, 15), date(2026, 3, 5))
    assert out == [(2026, 1), (2026, 2), (2026, 3)]


def test_months_between_same_month():
    out = months_between(date(2026, 5, 1), date(2026, 5, 28))
    assert out == [(2026, 5)]


def test_months_between_year_rollover():
    out = months_between(date(2025, 11, 1), date(2026, 2, 1))
    assert out == [(2025, 11), (2025, 12), (2026, 1), (2026, 2)]
