from datetime import date

import pandas as pd
import pytest

from bvb import adjust, db, valuation
from bvb.ingest import datagov


def test_available_year():
    assert valuation.available_year(date(2026, 5, 31)) == 2024
    assert valuation.available_year(date(2026, 6, 1)) == 2025


def test_standardize_bl_and_bank():
    bl = {
        datagov.norm(k): v
        for k, v in {
            "ACTIVE IMOBILIZATE - TOTAL": 100,
            "ACTIVE CIRCULANTE - TOTAL, din care:": 50,
            "CHELTUIELI IN AVANS": 5,
            "DATORII": 40,
            "CAPITALURI - TOTAL, din care:": 110,
            "Cifra de afaceri neta": 200,
            "VENITURI TOTALE": 210,
            "Profitul net": 0,
            "Pierdere neta": 15,
            "Numar mediu de salariati": 12,
        }.items()
    }
    s = datagov.standardize("BL", bl)
    assert (s["total_assets"], s["equity"], s["debts"], s["net_profit"], s["revenue"]) == (155, 110, 40, -15, 200)

    bank = {
        datagov.norm(k): v
        for k, v in {
            "Numerar si solduri de numerar la banci centrale": 10,
            "Active financiare evaluate la cost amortizat": 80,
            "Imobilizari corporale": 5,
            "Datorii financiare evaluate la cost amortizat": 85,
            "Capital social": 3,
            "Rezultatul reportat": 4,
            "Alte Rezerve": 2,
            "Profit sau (-) pierdere aferent(a) exercitiului": 1,
            "Profit sau pierdere aferent/a exercitiului": 1,
            "Cifra de afaceri neta": 9,
        }.items()
    }
    b = datagov.standardize("BANK", bank)
    assert (b["total_assets"], b["debts"], b["equity"], b["net_profit"], b["cash"]) == (95, 85, 10, 1, 10)
    assert b["revenue"] is None


def test_kind_of_old_and_new_file_names():
    assert datagov.kind_of("web_bl_bs_sl_an2024.txt") == "BL"
    assert datagov.kind_of("webblbsslan2010.txt") == "BL"
    assert datagov.kind_of("webir2015.txt") == "IR" and datagov.kind_of("webiran2015.txt") == "IR"
    assert datagov.kind_of("webuuan2018.txt") == "UU"
    assert datagov.kind_of("WEB_Inst_de_credit_2024.txt") == "BANK"
    assert datagov.kind_of("webifn2015.txt") is None


def test_filter_rows_and_descriptor():
    labels = datagov.parse_descriptor("CUI;CUI\r\nCAEN;CAEN\r\nCifra de afaceri neta;i1\r\n")
    assert labels == ["CUI", "CAEN", "Cifra de afaceri neta"]
    header, rows = datagov.filter_rows(iter(["CUI,CAEN,I1", "1,111,5", "22,222,7", "333,1,9"]), {"22", "333"})
    assert header == ["CUI", "CAEN", "I1"] and [r[0] for r in rows] == ["22", "333"]


@pytest.fixture
def con(tmp_path):
    c = db.connect(tmp_path / "v.duckdb")
    days = pd.bdate_range("2023-01-02", "2026-03-31")
    # actiuni gratuite 1:1 la 2025-01-02: pretul brut se injumatateste
    c.executemany(
        "INSERT INTO prices_eod (date, symbol, source, close, volume, adj_close) "
        "VALUES (?, 'AAA', 'bvb_hist', ?, 1, ?)",
        [[d.date(), 10.0 if d < pd.Timestamp("2025-01-02") else 5.0, 5.0] for d in days],
    )
    c.execute("INSERT INTO instruments (symbol, market, shares) VALUES ('AAA', 'REGS', 2000)")
    c.executemany(
        "INSERT INTO fundamentals (symbol, year, kind, revenue, net_profit, equity, total_assets, debts) "
        "VALUES ('AAA', ?, 'BL', ?, ?, ?, ?, ?)",
        [[2023, 1000, 100, 1000, 1500, 500], [2024, 1200, 200, 1100, 1700, 600]],
    )
    c.execute("INSERT INTO dividends (symbol, fiscal_year, amount, ex_date) VALUES ('AAA', 2024, 0.05, '2025-06-02')")
    adjust.run(c, ["AAA"])
    yield c
    c.close()


def test_market_cap_is_continuous_over_bonus_issue(con):
    mcap = valuation.market_cap_series(con, "AAA")
    assert mcap.iloc[0] == pytest.approx(10_000)  # 1000 actiuni * 10 lei
    assert mcap.iloc[-1] == pytest.approx(10_000)  # 2000 actiuni * 5 lei


def test_fundamentals_ratios_and_payout(con):
    f = valuation.fundamentals(con, "AAA")
    assert f.loc[2024, "roe"] == pytest.approx(200 / 1050)
    assert f.loc[2024, "revenue_growth"] == pytest.approx(0.2)
    assert f.loc[2024, "payout"] == pytest.approx(0.05 * 2000 / 200)


def test_multiples_use_point_in_time_fiscal_year(con):
    h = valuation.multiples_history(con, "AAA")
    assert h.loc["2025-05-31", "fiscal_year"] == 2023 and h.loc["2025-05-31", "pe"] == pytest.approx(100)
    assert h.loc["2025-06-30", "fiscal_year"] == 2024 and h.loc["2025-06-30", "pe"] == pytest.approx(50)
