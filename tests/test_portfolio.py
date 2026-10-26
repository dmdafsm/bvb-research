from datetime import date

import numpy as np
import pandas as pd
import pytest

from bvb import adjust, analytics, db, portfolio


@pytest.fixture
def con(tmp_path):
    """Baza mica: BET / BET-TR, doua actiuni, un dividend si actiuni gratuite."""
    c = db.connect(tmp_path / "t.duckdb")
    days = pd.bdate_range("2024-01-01", periods=60)
    rows = []
    for i, d in enumerate(days):
        rows.append([d.date(), "BET", 100 + i, None])
        rows.append([d.date(), "BET-TR", 100 + 1.1 * i, None])
        # AAA: creste liniar; actiuni gratuite 1:1 in ziua 30 (pretul se injumatateste, BVB ajusteaza)
        aaa = 10 + 0.1 * i
        rows.append([d.date(), "AAA", aaa / 2 if i >= 30 else aaa, aaa / 2])
        rows.append([d.date(), "BBB", 20.0 if i < 40 else 19.0, 20.0 if i < 40 else 19.0])
    c.executemany(
        "INSERT INTO prices_eod (date, symbol, source, close, volume, adj_close) VALUES (?, ?, 'bvb_hist', ?, 1000, ?)",
        [[r[0], r[1], r[2], r[3]] for r in rows])
    c.executemany("INSERT INTO instruments (symbol, market) VALUES (?, ?)",
                  [["BET", "INDEX"], ["BET-TR", "INDEX"], ["AAA", "REGS"], ["BBB", "REGS"]])
    c.execute("INSERT INTO capital_changes (symbol, record_date, shares_before, shares_after) VALUES (?, ?, 100, 200)",
              ["AAA", days[31].date()])
    # BBB: dividend 1 leu, data ex = ziua 40 (pretul scade cu dividendul)
    c.execute("INSERT INTO dividends (symbol, amount, ex_date) VALUES ('BBB', 1.0, ?)", [days[40].date()])
    adjust.run(c, ["AAA", "BBB"])
    yield c
    c.close()


def test_single_stock_no_costs_matches_total_return(con):
    for sym in ("AAA", "BBB"):
        r = portfolio.backtest(con, portfolio.Config(weights={sym: 1}, fee=0, tax=0))
        tr = analytics.series(con, [sym])[sym]
        assert r.nav.iloc[-1] / r.nav.iloc[0] == pytest.approx(tr.iloc[-1] / tr.iloc[0], rel=1e-9)


def test_dividend_tax_and_cash_mode(con):
    gross = portfolio.backtest(con, portfolio.Config(weights={"BBB": 1}, fee=0, tax=0))
    taxed = portfolio.backtest(con, portfolio.Config(weights={"BBB": 1}, fee=0, tax=0.1, dividends="cash"))
    assert taxed.metrics["dividend_tax"] == pytest.approx(0.1 * taxed.metrics["dividends_gross"])
    # 5000 actiuni * 1 leu brut, 10% impozit, tinute cash: 100.000 -> 95.000 + 4.500
    assert taxed.nav.iloc[-1] == pytest.approx(99_500)
    assert gross.nav.iloc[-1] == pytest.approx(100_000)


def test_rebalance_and_fees(con):
    r = portfolio.backtest(con, portfolio.Config(weights={"AAA": 0.5, "BBB": 0.5}, rebalance="monthly", fee=0.01, tax=0))
    assert r.metrics["fees_paid"] > 0
    assert (r.trades["date"] > r.nav.index[0].date()).any()   # au existat rebalansari
    assert r.nav.iloc[0] == pytest.approx(100_000, rel=0.011)  # doar comisionul initial


def test_dividend_tax_schedule():
    assert portfolio.dividend_tax(date(2015, 6, 1)) == 0.16
    assert portfolio.dividend_tax(date(2016, 6, 1)) == 0.05
    assert portfolio.dividend_tax(date(2023, 6, 1)) == 0.08
    assert portfolio.dividend_tax(date(2025, 6, 1)) == 0.10
    assert portfolio.dividend_tax(date(2026, 6, 1)) == 0.16


def test_parse_weights():
    assert portfolio.parse_weights("tlv,snp") == {"TLV": 0.5, "SNP": 0.5}
    assert portfolio.parse_weights("TLV=0.5,SNP,H2O") == {"TLV": 0.5, "SNP": 0.25, "H2O": 0.25}


def test_metrics_basic():
    idx = pd.bdate_range("2020-01-01", periods=5)
    v = pd.Series([100, 120, 90, 110, 130.0], index=idx)
    dd, peak, trough = analytics.max_drawdown(v)
    assert dd == pytest.approx(-0.25) and peak == date(2020, 1, 2) and trough == date(2020, 1, 3)
    idx2 = pd.DatetimeIndex(["2020-01-01", "2022-01-01"])
    assert analytics.cagr(pd.Series([100.0, 121.0], index=idx2)) == pytest.approx(0.1, abs=1e-3)
    assert np.isnan(analytics.cagr(pd.Series([100.0], index=idx[:1])))
