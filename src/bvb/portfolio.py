"""Backtest de portofoliu pe preturi de inchidere.

Model:
- tranzactionam la inchidere, in "actiuni ajustate" (adj_close), deci actiunile
  gratuite / splituri / consolidari nu mai trebuie tratate separat;
- dividendele (per actiune ajustata) se incaseaza la data ex, net de impozit,
  si se reinvestesc imediat in aceeasi actiune (`drip`) sau raman cash (`cash`);
- comision procentual pe valoarea tranzactionata, la cumparare si la vanzare;
- rebalansare la ponderile tinta la prima zi de tranzactionare a perioadei;
- un simbol fara tranzactii intr-o zi are pretul reportat (nu se blocheaza ordinul;
  pentru actiuni nelichide rezultatul e optimist).
"""

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from bvb import analytics

# Impozit pe dividende, persoane fizice rezidente (an data ex -> cota).
DIVIDEND_TAX = [(2016, 0.16), (2023, 0.05), (2025, 0.08), (2026, 0.10), (9999, 0.16)]

REBALANCE_FREQ = {"none": None, "monthly": "M", "quarterly": "Q", "yearly": "Y"}


def dividend_tax(day: date) -> float:
    """Cota pentru anul datei ex: 16% pana in 2015, 5% 2016-2022, 8% 2023-2024, 10% 2025, 16% din 2026."""
    for until, rate in DIVIDEND_TAX:
        if day.year < until:
            return rate
    return DIVIDEND_TAX[-1][1]


@dataclass
class Config:
    weights: dict[str, float]
    start: date | None = None
    end: date | None = None
    capital: float = 100_000.0
    rebalance: str = "none"          # none | monthly | quarterly | yearly
    fee: float = 0.0025              # comision pe tranzactie (fractie din valoare)
    tax: str | float = "auto"        # "auto" (cotele istorice), sau cota fixa
    dividends: str = "drip"          # drip | cash
    rf: float = 0.0


@dataclass
class Result:
    nav: pd.Series
    benchmark: pd.Series
    holdings: pd.DataFrame
    trades: pd.DataFrame
    dividends: pd.DataFrame
    metrics: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _dividends_adjusted(con, symbols: list[str]) -> pd.DataFrame:
    """Dividende per actiune ajustata (amount * cap_factor din ziua dinaintea datei ex)."""
    df = con.execute(f"""
        SELECT d.symbol, coalesce(d.ex_date, d.record_date) AS ex_date, d.amount,
               (SELECT arg_max(a.cap_factor, a.date) FROM prices_adj a
                WHERE a.symbol = d.symbol AND a.date < coalesce(d.ex_date, d.record_date)) AS cap_factor
        FROM dividends d
        WHERE d.symbol IN ({','.join('?' * len(symbols))}) AND d.amount > 0
          AND coalesce(d.ex_date, d.record_date) IS NOT NULL
    """, symbols).df()
    df["ex_date"] = pd.to_datetime(df["ex_date"])
    df["amount_adj"] = df["amount"] * df["cap_factor"].fillna(1.0)
    return df


def _rebalance_days(days: pd.DatetimeIndex, rule: str) -> set[pd.Timestamp]:
    freq = REBALANCE_FREQ[rule]
    if freq is None:
        return set()
    periods = days.to_period(freq)
    first = pd.Series(days, index=days).groupby(periods).first()
    return set(first.iloc[1:])  # prima zi a backtestului e cumpararea initiala


def backtest(con, cfg: Config) -> Result:
    symbols = list(cfg.weights)
    total = sum(cfg.weights.values())
    target = pd.Series({s: w / total for s, w in cfg.weights.items()})
    notes = []
    if abs(total - 1) > 1e-6:
        notes.append(f"Ponderile insumau {total:.4f}; au fost normalizate.")

    prices = analytics.series(con, symbols, field="adj_close", end=cfg.end)
    first_common = prices.dropna().index.min()
    if first_common is None or pd.isna(first_common):
        raise ValueError("Simbolurile nu au o perioada comuna de tranzactionare.")
    start = pd.Timestamp(cfg.start) if cfg.start else first_common
    if start < first_common:
        notes.append(f"Start mutat la {first_common.date()} (prima zi cu preturi pentru toate simbolurile).")
        start = first_common
    prices = prices[prices.index >= start]
    days = prices.index

    divs = _dividends_adjusted(con, symbols)
    divs = divs[(divs["ex_date"] > days[0]) & (divs["ex_date"] <= days[-1])]
    # data ex poate cadea intr-o zi fara sedinta pe calendarul BET -> urmatoarea zi
    divs["day"] = days[np.minimum(days.searchsorted(divs["ex_date"]), len(days) - 1)]
    divs_by_day = divs.groupby("day")

    rebal = _rebalance_days(days, cfg.rebalance)
    shares = pd.Series(0.0, index=symbols)
    cash = cfg.capital
    nav_rows, hold_rows, trades, div_rows = [], [], [], []

    def trade_to(target_values: pd.Series, px: pd.Series, day):
        nonlocal shares, cash
        current = shares * px
        delta = target_values - current
        for s, dv in delta.items():
            if abs(dv) < 1e-6:
                continue
            q = dv / px[s]
            cost = abs(dv) * cfg.fee
            shares[s] += q
            cash -= dv + cost
            trades.append({"date": day.date(), "symbol": s, "shares": q, "price": px[s], "value": dv, "fee": cost})

    for i, day in enumerate(days):
        px = prices.loc[day]

        if day in divs_by_day.groups:
            for d in divs_by_day.get_group(day).itertuples():
                if shares[d.symbol] <= 0:
                    continue
                rate = dividend_tax(d.ex_date.date()) if cfg.tax == "auto" else float(cfg.tax)
                gross = shares[d.symbol] * d.amount_adj
                net = gross * (1 - rate)
                cash += net
                div_rows.append({"date": day.date(), "symbol": d.symbol, "gross": gross, "tax": gross - net})
                if cfg.dividends == "drip":
                    q = net / (px[d.symbol] * (1 + cfg.fee))
                    shares[d.symbol] += q
                    cash -= q * px[d.symbol] * (1 + cfg.fee)
                    trades.append({"date": day.date(), "symbol": d.symbol, "shares": q, "price": px[d.symbol],
                                   "value": q * px[d.symbol], "fee": q * px[d.symbol] * cfg.fee})

        if i == 0 or day in rebal:
            nav = cash + (shares * px).sum()
            # rezervam comisionul estimat ca sa nu intram pe cash negativ
            turnover = (target * nav - shares * px).abs().sum()
            trade_to(target * (nav - turnover * cfg.fee), px, day)

        value = (shares * px).sum()
        nav_rows.append(cash + value)
        hold_rows.append(shares * px)

    nav = pd.Series(nav_rows, index=days, name="portfolio")
    bench = analytics.benchmark_series(con, start=days[0].date(), end=days[-1].date()).reindex(days).ffill()
    bench = bench / bench.iloc[0] * cfg.capital
    holdings = pd.DataFrame(hold_rows, index=days)

    m = analytics.metrics(nav, bench, cfg.rf)
    m["bench_cagr"] = analytics.cagr(bench)
    m["bench_max_drawdown"] = analytics.max_drawdown(bench)[0]
    m["bench_volatility"] = analytics.volatility(bench)
    m["final_value"] = nav.iloc[-1]
    tr = pd.DataFrame(trades)
    dv = pd.DataFrame(div_rows)
    m["fees_paid"] = tr["fee"].sum() if len(tr) else 0.0
    m["dividends_gross"] = dv["gross"].sum() if len(dv) else 0.0
    m["dividend_tax"] = dv["tax"].sum() if len(dv) else 0.0
    m["turnover_per_year"] = (tr["value"].abs().sum() - cfg.capital) / nav.mean() / max(
        (days[-1] - days[0]).days / 365.25, 1e-9) if len(tr) else 0.0
    if bench.name != analytics.BENCHMARK or days[0] < pd.Timestamp("2014-09-19"):
        notes.append("Inainte de 2014-09-19 benchmark-ul e BET (fara dividende).")
    return Result(nav, bench, holdings, tr, dv, m, notes)


def yearly_returns(r: Result) -> pd.DataFrame:
    """Randament pe ani calendaristici (primul si ultimul an pot fi partiale)."""
    df = pd.DataFrame({"portofoliu": r.nav, "BET-TR": r.benchmark})
    ends = df.groupby(df.index.year).last()
    starts = ends.shift(1)
    starts.iloc[0] = df.iloc[0]
    return ends / starts - 1


def parse_weights(text: str) -> dict[str, float]:
    """'TLV=0.3,SNP=0.3,H2O' -> ponderi; simbolurile fara pondere impart restul egal."""
    weights, rest = {}, []
    for part in filter(None, (p.strip() for p in text.split(","))):
        if "=" in part:
            s, w = part.split("=", 1)
            weights[s.strip().upper()] = float(w)
        else:
            rest.append(part.upper())
    if rest:
        left = max(1 - sum(weights.values()), 0) if weights else 1.0
        for s in rest:
            weights[s] = left / len(rest)
    return weights
