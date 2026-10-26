"""Analiza pe actiune: randamente, risc, lichiditate, dividende.

Conventii:
- calendarul = zilele de tranzactionare ale indicelui BET;
- in zilele fara tranzactii pretul se reporteaza (randament 0), deci pentru
  actiunile nelichide volatilitatea si beta sunt subestimate; de aceea
  raportam mereu si lichiditatea (% zile cu tranzactii, valoare medie zilnica);
- randamentele folosesc `tr_close` (dividende brute reinvestite), daca nu se cere altfel.
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd

TRADING_DAYS = 252
CALENDAR_INDEX = "BET"
BENCHMARK = "BET-TR"
BENCHMARK_FALLBACK = "BET"  # BET-TR exista doar din 2014


def calendar(con, start=None, end=None) -> pd.DatetimeIndex:
    days = con.execute(
        "SELECT date FROM prices_eod WHERE symbol = ? AND source = 'bvb_hist' "
        "AND date >= coalesce(?, DATE '1990-01-01') AND date <= coalesce(?, DATE '2100-01-01') ORDER BY date",
        [CALENDAR_INDEX, start, end]).df()["date"]
    return pd.DatetimeIndex(pd.to_datetime(days))


def series(con, symbols: list[str], field: str = "tr_close", start=None, end=None) -> pd.DataFrame:
    """Serii zilnice pe calendarul BET, reportate inainte (doar dupa prima tranzactie)."""
    q = f"""
        SELECT date, symbol, {field} AS v FROM prices_adj
        WHERE symbol IN ({','.join('?' * len(symbols))})
        UNION ALL
        SELECT date, symbol, close AS v FROM prices WHERE symbol IN ({','.join('?' * len(symbols))})
            AND symbol IN (SELECT symbol FROM instruments WHERE market = 'INDEX')
    """
    df = con.execute(q, symbols + symbols).df()
    wide = df.pivot_table(index="date", columns="symbol", values="v", aggfunc="last")
    wide.index = pd.to_datetime(wide.index)
    days = calendar(con, start, end)
    wide = wide.reindex(wide.index.union(days)).sort_index().ffill().reindex(days)
    return wide.reindex(columns=symbols)


def benchmark_series(con, start=None, end=None) -> pd.Series:
    """BET-TR, prelungit inapoi cu BET (fara dividende) inainte de 2014."""
    s = series(con, [BENCHMARK, BENCHMARK_FALLBACK], start=start, end=end)
    tr, px = s[BENCHMARK], s[BENCHMARK_FALLBACK]
    first = tr.first_valid_index()
    if first is None:
        return px.rename(BENCHMARK_FALLBACK)
    out = tr.copy()
    before = out.index < first
    out[before] = px[before] * tr[first] / px[first]
    return out.rename(BENCHMARK)


# --- metrici pe o serie de valori (pret / NAV) --------------------------------

def returns(values: pd.Series) -> pd.Series:
    return values.dropna().pct_change().dropna()


def cagr(values: pd.Series) -> float:
    v = values.dropna()
    if len(v) < 2 or v.iloc[0] <= 0:
        return np.nan
    years = (v.index[-1] - v.index[0]).days / 365.25
    return (v.iloc[-1] / v.iloc[0]) ** (1 / years) - 1 if years > 0 else np.nan


def volatility(values: pd.Series) -> float:
    return returns(values).std() * np.sqrt(TRADING_DAYS)


def max_drawdown(values: pd.Series) -> tuple[float, date | None, date | None]:
    """-> (drawdown maxim negativ, data varfului, data minimului)"""
    v = values.dropna()
    if v.empty:
        return np.nan, None, None
    peak = v.cummax()
    dd = v / peak - 1
    trough = dd.idxmin()
    peak_day = v[:trough].idxmax()
    return float(dd.min()), peak_day.date(), trough.date()


def sharpe(values: pd.Series, rf: float = 0.0) -> float:
    r = returns(values) - rf / TRADING_DAYS
    return r.mean() / r.std() * np.sqrt(TRADING_DAYS) if r.std() > 0 else np.nan


def sortino(values: pd.Series, rf: float = 0.0) -> float:
    r = returns(values) - rf / TRADING_DAYS
    downside = np.sqrt((np.minimum(r, 0) ** 2).mean())
    return r.mean() / downside * np.sqrt(TRADING_DAYS) if downside > 0 else np.nan


def beta_corr(values: pd.Series, bench: pd.Series) -> tuple[float, float]:
    r = pd.concat([returns(values), returns(bench)], axis=1, join="inner").dropna()
    if len(r) < 20:
        return np.nan, np.nan
    cov = np.cov(r.iloc[:, 0], r.iloc[:, 1])
    return cov[0, 1] / cov[1, 1], float(r.corr().iloc[0, 1])


def metrics(values: pd.Series, bench: pd.Series | None = None, rf: float = 0.0) -> dict:
    dd, peak, trough = max_drawdown(values)
    out = {
        "cagr": cagr(values),
        "volatility": volatility(values),
        "sharpe": sharpe(values, rf),
        "sortino": sortino(values, rf),
        "max_drawdown": dd,
        "dd_peak": peak,
        "dd_trough": trough,
    }
    if bench is not None:
        out["beta"], out["corr"] = beta_corr(values, bench)
        active = pd.concat([returns(values), returns(bench)], axis=1, join="inner").dropna()
        diff = active.iloc[:, 0] - active.iloc[:, 1]
        te = diff.std() * np.sqrt(TRADING_DAYS)
        out["tracking_error"] = te
        out["info_ratio"] = diff.mean() * TRADING_DAYS / te if te > 0 else np.nan
    return out


# --- lichiditate si dividende --------------------------------------------------

def liquidity(con, symbols: list[str], end: date, days: int = 365) -> pd.DataFrame:
    """% zile cu tranzactii si valoarea medie zilnica (RON) pe ultimele `days` zile calendaristice."""
    start = end - timedelta(days=days)
    n_days = len(calendar(con, start, end))
    df = con.execute(f"""
        SELECT symbol,
               count(*) FILTER (WHERE volume > 0)         AS traded_days,
               sum(coalesce(value, volume * close)) / ?   AS adv_value,
               median(coalesce(value, volume * close)) FILTER (WHERE volume > 0) AS median_value
        FROM prices
        WHERE symbol IN ({','.join('?' * len(symbols))}) AND date > ? AND date <= ?
        GROUP BY symbol
    """, [max(n_days, 1), *symbols, start, end]).df().set_index("symbol")
    df["pct_days_traded"] = df["traded_days"] / max(n_days, 1)
    return df.reindex(symbols)


def trailing_dividend_yield(con, symbols: list[str], end: date) -> pd.Series:
    """Dividende cu data ex in ultimele 12 luni / ultimul pret (brut).

    Dividendele de dinaintea unui eveniment de capital (actiuni gratuite,
    consolidare) sunt aduse la numarul actual de actiuni prin cap_factor."""
    df = con.execute(f"""
        WITH d AS (
            SELECT d.symbol, sum(d.amount
                * coalesce((SELECT arg_max(a.cap_factor, a.date) FROM prices_adj a
                            WHERE a.symbol = d.symbol AND a.date < coalesce(d.ex_date, d.record_date)), 1)
                / coalesce((SELECT arg_max(z.cap_factor, z.date) FROM prices_adj z
                            WHERE z.symbol = d.symbol AND z.date <= ?), 1)) AS div12
            FROM dividends d
            WHERE d.symbol IN ({','.join('?' * len(symbols))})
              AND coalesce(d.ex_date, d.record_date) > ?::DATE - INTERVAL 1 YEAR
              AND coalesce(d.ex_date, d.record_date) <= ?
            GROUP BY d.symbol
        ), p AS (
            SELECT symbol, arg_max(close, date) AS last_close FROM prices
            WHERE symbol IN ({','.join('?' * len(symbols))}) AND date <= ? GROUP BY symbol
        )
        SELECT p.symbol, coalesce(d.div12, 0) / p.last_close AS div_yield
        FROM p LEFT JOIN d USING (symbol)
    """, [end, *symbols, end, end, *symbols, end]).df()
    return df.set_index("symbol")["div_yield"].reindex(symbols)


# --- raport pe actiune si screener ---------------------------------------------

WINDOWS = {"1y": 1, "3y": 3, "5y": 5, "10y": 10}


def _window(values: pd.Series, end: pd.Timestamp, years: int) -> pd.Series:
    start = end - pd.DateOffset(years=years)
    v = values[(values.index >= start) & (values.index <= end)].dropna()
    # fereastra e valida doar daca seria acopera aproape tot intervalul
    if v.empty or (v.index[0] - start).days > 31:
        return pd.Series(dtype=float)
    return v


def stock_report(con, symbol: str, end: date | None = None, rf: float = 0.0) -> dict:
    data = series(con, [symbol], end=end)[symbol]
    price = series(con, [symbol], field="adj_close", end=end)[symbol]
    bench = benchmark_series(con, end=end)
    last = data.last_valid_index()
    if last is None:
        raise ValueError(f"Nu exista preturi pentru {symbol}")
    rows = {}
    for name, years in WINDOWS.items():
        v = _window(data, last, years)
        if v.empty:
            continue
        m = metrics(v, bench.reindex(v.index), rf)
        m["price_cagr"] = cagr(_window(price, last, years))
        m["bench_cagr"] = cagr(bench.reindex(v.index))
        rows[name] = m
    info = con.execute(
        "SELECT name, isin, market, segment, category, activity, shares, listing_date FROM instruments WHERE symbol = ?",
        [symbol]).df().iloc[0].to_dict()
    close = con.execute("SELECT arg_max(close, date) FROM prices WHERE symbol = ? AND date <= ?",
                        [symbol, last.date()]).fetchone()[0]
    info["last_date"] = last.date()
    info["last_close"] = close
    info["market_cap"] = close * info["shares"] if info.get("shares") else None
    info["div_yield_12m"] = trailing_dividend_yield(con, [symbol], last.date()).iloc[0]
    liq = liquidity(con, [symbol], last.date()).iloc[0]
    info["pct_days_traded_1y"] = liq["pct_days_traded"]
    info["adv_value_1y"] = liq["adv_value"]
    divs = con.execute(
        "SELECT fiscal_year, amount, ex_date, pay_date FROM dividends WHERE symbol = ? "
        "ORDER BY coalesce(ex_date, record_date) DESC NULLS LAST LIMIT 10", [symbol]).df()
    return {"info": info, "windows": pd.DataFrame(rows), "dividends": divs}


def screen(con, market: str = "REGS", years: int = 3, end: date | None = None, rf: float = 0.0) -> pd.DataFrame:
    symbols = [r[0] for r in con.execute(
        "SELECT symbol FROM instruments WHERE market = ? ORDER BY symbol", [market]).fetchall()]
    data = series(con, symbols, end=end)
    bench = benchmark_series(con, end=end)
    last = data.index[-1]
    rows = []
    for s in symbols:
        v = _window(data[s], last, years)
        if v.empty:
            continue
        m = metrics(v, bench.reindex(v.index), rf)
        rows.append({"symbol": s, **{k: m[k] for k in ("cagr", "volatility", "sharpe", "max_drawdown", "beta")}})
    df = pd.DataFrame(rows).set_index("symbol")
    liq = liquidity(con, list(df.index), last.date())
    info = con.execute(
        f"SELECT symbol, shares FROM instruments WHERE symbol IN ({','.join('?' * len(df))})", list(df.index)
    ).df().set_index("symbol")
    closes = con.execute(
        f"SELECT symbol, arg_max(close, date) AS close FROM prices WHERE symbol IN ({','.join('?' * len(df))}) "
        "AND date <= ? GROUP BY symbol", [*df.index, last.date()]).df().set_index("symbol")
    df["market_cap_mn"] = closes["close"] * info["shares"] / 1e6
    df["div_yield"] = trailing_dividend_yield(con, list(df.index), last.date())
    df["adv_value_k"] = liq["adv_value"] / 1e3
    df["pct_days_traded"] = liq["pct_days_traded"]
    return df.sort_values("market_cap_mn", ascending=False)
