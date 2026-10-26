"""Multipli de evaluare si indicatori de calitate din situatiile financiare anuale.

- Datele anuale sunt considerate disponibile din 1 iunie a anului urmator
  (termenul de depunere la MF si de publicare a raportului anual), ca sa nu
  folosim informatii "din viitor" in evaluarile istorice.
- Capitalizarea istorica: close_t * actiuni_acum * cap_factor_t (aduce numarul de
  actiuni inapoi peste actiunile gratuite / splituri / consolidari; nu prinde
  emisiunile cu bani sau rascumpararile).
- Situatiile sunt INDIVIDUALE (nu consolidate): pentru holdinguri si grupuri cu
  filiale importante, multiplii difera de cei raportati pe grup.
"""

from datetime import date

import numpy as np
import pandas as pd

AVAILABLE_MONTH = 6  # luna din anul urmator din care datele anuale sunt publice


def available_year(as_of: date) -> int:
    """Ultimul exercitiu financiar disponibil la data `as_of`."""
    return as_of.year - 1 if as_of.month >= AVAILABLE_MONTH else as_of.year - 2


def fundamentals(con, symbol: str) -> pd.DataFrame:
    df = (
        con.execute(
            """
        SELECT year, kind, revenue, total_revenue, net_profit, equity, total_assets, debts, cash, employees
        FROM fundamentals_annual WHERE symbol = ? ORDER BY year
    """,
            [symbol],
        )
        .df()
        .set_index("year")
    )
    if df.empty:
        return df
    df["net_margin"] = df["net_profit"] / df["revenue"].where(df["revenue"] > 0)
    df["roe"] = df["net_profit"] / df["equity"].rolling(2, min_periods=1).mean().where(lambda x: x > 0)
    df["roa"] = df["net_profit"] / df["total_assets"].rolling(2, min_periods=1).mean().where(lambda x: x > 0)
    df["debt_to_equity"] = df["debts"] / df["equity"].where(df["equity"] > 0)
    df["revenue_growth"] = df["revenue"].pct_change(fill_method=None)
    df["profit_growth"] = df["net_profit"].pct_change(fill_method=None).where(df["net_profit"].shift(1) > 0)
    div = dividends_per_fiscal_year(con, symbol)
    df["dividends_total"] = div.reindex(df.index)
    df["payout"] = df["dividends_total"] / df["net_profit"].where(df["net_profit"] > 0)
    return df


def dividends_per_fiscal_year(con, symbol: str) -> pd.Series:
    """Total dividende distribuite pe exercitiu (RON) = suma(dividend * actiuni la data ex)."""
    df = con.execute(
        """
        SELECT d.fiscal_year, sum(d.amount * i.shares * coalesce(
            (SELECT arg_max(a.cap_factor, a.date) FROM prices_adj a
             WHERE a.symbol = d.symbol AND a.date < coalesce(d.ex_date, d.record_date)), 1)) AS total
        FROM dividends d JOIN instruments i USING (symbol)
        WHERE d.symbol = ? AND d.fiscal_year IS NOT NULL
        GROUP BY d.fiscal_year
    """,
        [symbol],
    ).df()
    return df.set_index("fiscal_year")["total"]


def market_cap_series(con, symbol: str) -> pd.Series:
    df = con.execute(
        """
        SELECT a.date, a.close * i.shares * a.cap_factor AS mcap
        FROM prices_adj a JOIN instruments i USING (symbol)
        WHERE a.symbol = ? AND i.shares IS NOT NULL ORDER BY a.date
    """,
        [symbol],
    ).df()
    return pd.Series(df["mcap"].values, index=pd.to_datetime(df["date"]), name="mcap")


def multiples_history(con, symbol: str, freq: str = "ME") -> pd.DataFrame:
    """P/E, P/B, P/S lunar, folosind la fiecare data ultimul exercitiu disponibil atunci."""
    mcap = market_cap_series(con, symbol)
    fund = fundamentals(con, symbol)
    if mcap.empty or fund.empty:
        return pd.DataFrame()
    m = mcap.resample(freq).last().dropna()
    fy = pd.Series([available_year(d.date()) for d in m.index], index=m.index)
    f = fund.reindex(fy.values)
    f.index = m.index
    return pd.DataFrame(
        {
            "mcap": m,
            "fiscal_year": fy,
            "pe": m / f["net_profit"].where(f["net_profit"] > 0),
            "pb": m / f["equity"].where(f["equity"] > 0),
            "ps": m / f["revenue"].where(f["revenue"] > 0),
        }
    ).dropna(subset=["fiscal_year"])


def current_multiples(con, symbols: list[str], as_of: date | None = None) -> pd.DataFrame:
    rows = []
    for s in symbols:
        hist = multiples_history(con, s)
        if hist.empty:
            continue
        if as_of:
            hist = hist[hist.index <= pd.Timestamp(as_of)]
        mcap = market_cap_series(con, s)
        if as_of:
            mcap = mcap[mcap.index <= pd.Timestamp(as_of)]
        last_day = mcap.index[-1]
        fy = available_year(last_day.date())
        fund = fundamentals(con, s)
        if fy not in fund.index:
            fy = fund.index[fund.index <= fy].max() if (fund.index <= fy).any() else None
        if fy is None or pd.isna(fy):
            continue
        f = fund.loc[fy]
        cap = mcap.iloc[-1]
        pe = cap / f["net_profit"] if f["net_profit"] and f["net_profit"] > 0 else np.nan
        pb = cap / f["equity"] if f["equity"] and f["equity"] > 0 else np.nan
        # pozitia multiplului actual fata de propriul istoric pe 10 ani (0 = cel mai ieftin)
        h10 = hist[hist.index > last_day - pd.DateOffset(years=10)]
        rows.append(
            {
                "symbol": s,
                "fiscal_year": int(fy),
                "kind": f["kind"],
                "mcap_mn": cap / 1e6,
                "pe": pe,
                "pb": pb,
                "ps": cap / f["revenue"] if f["revenue"] and f["revenue"] > 0 else np.nan,
                "roe": f["roe"],
                "net_margin": f["net_margin"],
                "debt_to_equity": f["debt_to_equity"],
                "revenue_growth": f["revenue_growth"],
                "payout": f["payout"],
                "pe_pctile_10y": (h10["pe"].dropna() < pe).mean()
                if pe == pe and h10["pe"].notna().sum() >= 24
                else np.nan,
                "pb_pctile_10y": (h10["pb"].dropna() < pb).mean()
                if pb == pb and h10["pb"].notna().sum() >= 24
                else np.nan,
            }
        )
    return pd.DataFrame(rows).set_index("symbol") if rows else pd.DataFrame()
