"""Istoric zilnic din Yahoo Finance (ticker '<SIMBOL>.RO').

API neoficial; il folosim pentru istoricul mai vechi de ~30 de zile (pe care
BVB nu il mai ofera public) si pentru validarea preturilor BVB.
Atentie: 'close' de la Yahoo e ajustat pentru splituri, nu si pentru dividende;
'adj_close' e ajustat pentru ambele.
"""

import time
from datetime import date, datetime, timedelta, timezone

import httpx

from bvb.config import REQUEST_DELAY, USER_AGENT

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"


def to_ticker(symbol: str) -> str:
    return f"{symbol}.RO"


RATE_LIMIT_WAIT = 120  # secunde


class RateLimited(Exception):
    pass


def fetch_chart(client: httpx.Client, ticker: str) -> dict | None:
    """Raspunsul 'chart.result[0]' sau None daca tickerul nu exista."""
    params = {
        "period1": 0,
        "period2": int(time.time()),
        "interval": "1d",
        "events": "div,split",
    }
    r = client.get(CHART_URL.format(ticker=ticker), params=params)
    if r.status_code == 404:
        return None
    if r.status_code == 429:
        raise RateLimited(ticker)
    r.raise_for_status()
    result = r.json()["chart"]["result"]
    return result[0] if result else None


def _local_date(ts: int, gmtoffset: int) -> date:
    return (datetime.fromtimestamp(ts, tz=timezone.utc) + timedelta(seconds=gmtoffset)).date()


def parse_chart(symbol: str, chart: dict) -> tuple[list[list], list[list]]:
    """-> (randuri prices_eod, randuri corporate_events)"""
    offset = chart["meta"].get("gmtoffset", 0)
    stamps = chart.get("timestamp") or []
    quote = chart["indicators"]["quote"][0]
    adj = (chart["indicators"].get("adjclose") or [{}])[0].get("adjclose") or [None] * len(stamps)

    prices = []
    for i, ts in enumerate(stamps):
        close = quote["close"][i]
        if close is None:
            continue
        volume = quote["volume"][i]
        prices.append([
            _local_date(ts, offset), symbol, "yahoo",
            quote["open"][i], quote["high"][i], quote["low"][i], close,
            int(volume) if volume is not None else None, adj[i],
        ])

    events = []
    for ev in (chart.get("events", {}).get("dividends") or {}).values():
        events.append([_local_date(ev["date"], offset), symbol, "yahoo", "dividend", ev["amount"], None])
    for ev in (chart.get("events", {}).get("splits") or {}).values():
        events.append([_local_date(ev["date"], offset), symbol, "yahoo", "split", None,
                       ev["numerator"] / ev["denominator"]])
    return prices, events


def store(con, prices: list[list], events: list[list]) -> int:
    if prices:
        con.executemany(
            """
            INSERT OR REPLACE INTO prices_eod
                (date, symbol, source, open, high, low, close, volume, adj_close)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            prices,
        )
    if events:
        con.executemany(
            "INSERT OR REPLACE INTO corporate_events (date, symbol, source, kind, amount, ratio) VALUES (?, ?, ?, ?, ?, ?)",
            events,
        )
    return len(prices)


def ingest(con, symbols: list[str], log=print) -> dict[str, int]:
    """Descarca istoricul pentru fiecare simbol; marcheaza in `instruments.yahoo`
    tickerul gasit sau '' daca Yahoo nu il are.

    La limitare de rata (429) asteapta o data si reincearca; daca persista,
    se opreste si intoarce ce a reusit (rularea urmatoare continua de acolo).
    """
    counts = {}
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True) as client:
        for symbol in symbols:
            ticker = to_ticker(symbol)
            try:
                chart = fetch_chart(client, ticker)
            except RateLimited:
                log(f"{symbol}: limita de rata Yahoo, astept {RATE_LIMIT_WAIT}s")
                time.sleep(RATE_LIMIT_WAIT)
                try:
                    chart = fetch_chart(client, ticker)
                except RateLimited:
                    log("Yahoo limiteaza in continuare; oprit. Reia mai tarziu.")
                    break
            if chart is None or not chart.get("timestamp"):
                con.execute("UPDATE instruments SET yahoo = '' WHERE symbol = ?", [symbol])
                log(f"{symbol}: lipsa pe Yahoo")
                counts[symbol] = 0
            else:
                prices, events = parse_chart(symbol, chart)
                counts[symbol] = store(con, prices, events)
                con.execute("UPDATE instruments SET yahoo = ? WHERE symbol = ?", [ticker, symbol])
                log(f"{symbol}: {counts[symbol]} zile, {len(events)} evenimente")
            time.sleep(REQUEST_DELAY / 2)
    return counts
