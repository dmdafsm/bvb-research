from datetime import date
from pathlib import Path

import pytest

from bvb import db
from bvb.ingest import bvb_summary, yahoo
from bvb.reconcile import reconcile

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def con(tmp_path):
    c = db.connect(tmp_path / "test.duckdb")
    yield c
    c.close()


@pytest.mark.parametrize(
    "text, expected",
    [
        ("12.345.678,90", 12345678.9),
        ("21,7400", 21.74),
        ("-2,75", -2.75),
        ("1.234", 1234.0),
        ("", None),
        ("-", None),
    ],
)
def test_parse_number(text, expected):
    assert bvb_summary.parse_number(text) == expected


def test_parse_summary_fixture():
    # fixture sintetic, cu structura paginii BVB (randul "Nu exista date" e sarit)
    rows = bvb_summary.parse_summary((FIXTURES / "bvb_summary_synthetic.html").read_text())
    assert [r["symbol"] for r in rows] == ["AAA", "BBB", "CCC", "DDD"]
    assert rows[0] == {
        "symbol": "AAA",
        "market": "REGS",
        "trades": 1234,
        "volume": 567890,
        "value": 12345678.9,
        "open": 21.74,
        "low": 21.5,
        "high": 21.98,
        "avg_price": 21.74,
        "close": 21.8,
        "ref_price": 21.6,
        "change_pct": 0.93,
    }
    ccc = rows[2]  # fara tranzactii: pretul de deschidere lipseste, nu e zero
    assert (ccc["open"], ccc["close"], ccc["volume"]) == (None, 0.45, 0)
    assert rows[1]["change_pct"] == -1.44


def test_parse_summary_empty_and_missing_columns():
    assert bvb_summary.parse_summary("<html></html>") == []
    with pytest.raises(ValueError):
        bvb_summary.parse_summary('<table id="gv"><thead><tr><th>Simbol</th></tr></thead></table>')


CHART = {
    "meta": {"gmtoffset": 10800},
    "timestamp": [1792535400, 1792652400, 1792738800],  # 20.10 22:30 UTC = 21.10 ora Romaniei
    "indicators": {
        "quote": [
            {
                "open": [10.0, None, 11.0],
                "high": [10.5, None, 11.5],
                "low": [9.5, None, 10.5],
                "close": [10.2, None, 11.2],
                "volume": [1000, None, 2000],
            }
        ],
        "adjclose": [{"adjclose": [9.9, None, 11.2]}],
    },
    "events": {
        "dividends": {"1792652400": {"amount": 0.5, "date": 1792652400}},
        "splits": {"1792738800": {"numerator": 2, "denominator": 1, "date": 1792738800}},
    },
}


def test_parse_chart_skips_empty_bars_and_reads_events():
    prices, events = yahoo.parse_chart("ABC", CHART)
    assert [p[0] for p in prices] == [date(2026, 10, 21), date(2026, 10, 23)]
    assert prices[0][1:] == ["ABC", "yahoo", 10.0, 10.5, 9.5, 10.2, 1000, 9.9]
    assert sorted((e[3], e[4], e[5]) for e in events) == [("dividend", 0.5, None), ("split", None, 2.0)]


def test_prices_view_prefers_bvb_and_reconcile(con):
    day = date(2026, 10, 21)
    row = {
        "symbol": "ABC",
        "market": "REGS",
        "open": 1,
        "high": 1,
        "low": 1,
        "close": 10.0,
        "avg_price": 1,
        "ref_price": 1,
        "change_pct": 0,
        "volume": 1,
        "value": 1,
        "trades": 1,
    }
    bvb_summary.store(con, day, [row])
    yahoo.store(con, [[day, "ABC", "yahoo", 1, 1, 1, 10.5, 1, 10.5]], [])

    assert con.execute("SELECT source, close FROM prices WHERE symbol = 'ABC'").fetchall() == [("bvb", 10.0)]
    assert con.execute("SELECT first_seen, last_seen FROM instruments").fetchone() == (day, day)

    df = reconcile(con, "yahoo", threshold=0.01)
    assert df.loc[0, "mismatches"] == 1 and df.loc[0, "max_diff_pct"] == 5.0


def test_bvb_history_parse_aligns_adjusted_and_drops_open_session():
    from datetime import UTC, datetime

    from bvb.ingest import bvb_history

    def d(day):
        return int(datetime(2026, 10, day, tzinfo=UTC).timestamp())

    raw = {
        "s": "ok",
        "t": [d(22), d(23), d(26)],
        "o": [1, 2, 3],
        "h": [1, 2, 3],
        "l": [1, 2, 3],
        "c": [10.0, 11.0, 12.0],
        "v": [100, 200, 50],
    }
    adj = {"s": "ok", "t": [d(22), d(23), d(26)], "c": [9.0, 11.0, 12.0]}

    rows = bvb_history.parse("ABC", raw, adj, until=date(2026, 10, 23))
    assert [(r[0], r[6], r[7], r[8]) for r in rows] == [
        (date(2026, 10, 22), 10.0, 100, 9.0),
        (date(2026, 10, 23), 11.0, 200, 11.0),
    ]
    assert bvb_history.parse("ABC", {"s": "no_data"}, None, until=date(2026, 10, 23)) == []


def test_last_complete_day():
    from datetime import datetime

    from bvb.ingest.bvb_history import TZ, last_complete_day

    assert last_complete_day(datetime(2026, 10, 26, 14, 0, tzinfo=TZ)) == date(2026, 10, 25)
    assert last_complete_day(datetime(2026, 10, 26, 18, 30, tzinfo=TZ)) == date(2026, 10, 26)


def test_issuer_parse_fixture():
    from bvb.ingest import issuer

    data = issuer.parse("AAA", (FIXTURES / "issuer_synthetic.html").read_text())
    inst = data["instrument"]
    assert inst["name"] == "ALFA EXEMPLU S.A."
    assert inst["isin"] == "RO0000AAA001"  # din dvInfo, nu din tabelul de preturi
    assert (inst["segment"], inst["category"]) == ("Principal", "Premium")
    assert inst["cui"] == "12345678"
    assert inst["shares"] == 1_250_000_000
    assert inst["nominal_value"] == 0.1
    assert inst["listing_date"] == date(2005, 3, 15)

    assert len(data["dividends"]) == 3  # randul fara suma e sarit
    d = data["dividends"][0]
    assert (d["fiscal_year"], d["amount"], d["ex_date"], d["pay_date"]) == (
        2025,
        0.095,
        date(2026, 5, 14),
        date(2026, 6, 5),
    )
    assert data["dividends"][2]["pay_date"] is None

    assert len(data["capital"]) == 2
    c = data["capital"][0]
    assert (c["record_date"], c["shares_before"], c["shares_after"]) == (date(2022, 7, 6), 1_000_000_000, 1_250_000_000)
    assert data["capital"][1]["ref_date"] is None

    holders = data["shareholders"]
    assert holders[0]["holder"].startswith("STATUL ROMAN")
    assert len(holders) == 3  # fara randul TOTAL
    assert (holders[0]["as_of"], holders[0]["shares"], holders[0]["pct"]) == (date(2026, 9, 30), 650_000_000, 52.0)
