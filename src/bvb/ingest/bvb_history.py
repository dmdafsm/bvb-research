"""Istoric zilnic complet din API-ul graficului de pe bvb.ro (TradingView UDF).

Endpoint: https://wapi.bvb.ro/api/history?symbol=TLV&from=..&to=..&rs=1D&ajust=0|1&countback=..
Raspuns: {"s": "ok", "t": [...], "o": [...], "h": [...], "l": [...], "c": [...], "v": [...]}
- `t` = miezul noptii UTC al zilei de tranzactionare;
- `ajust=0` preturi brute, `ajust=1` preturi ajustate de BVB (le pastram in `adj_close`).
Folosit cu aprobarea explicita a utilizatorului, doar pentru uz personal.
"""

import time
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import httpx

from bvb.config import BVB_BASE, REQUEST_DELAY, USER_AGENT

URL = "https://wapi.bvb.ro/api/history"
SOURCE = "bvb_hist"
TZ = ZoneInfo("Europe/Bucharest")
SESSION_END = (18, 30)  # dupa aceasta ora bara zilei curente e finala

INDICES = ["BET", "BET-TR", "BET-TRN", "BET-FI", "BET-NG", "BET-EF", "BET-BK",
           "BET-XT", "BET-XT-TR", "BETPlus", "BETAeRO", "ROTX"]


def fetch(client: httpx.Client, symbol: str, adjusted: bool) -> dict:
    params = {
        "symbol": symbol,
        "from": 631152000,  # 1990-01-01
        "to": int(time.time()) + 86400,
        "rs": "1D",
        "ajust": int(adjusted),
        "countback": 20000,
        "currencyCode": "RON",
    }
    r = client.get(URL, params=params)
    r.raise_for_status()
    return r.json()


SYMBOLS_URL = "https://wapi.bvb.ro/api/symbols"


def fetch_metadata(client: httpx.Client, symbol: str) -> dict:
    """Sector, industrie si moneda din API-ul graficului."""
    r = client.get(SYMBOLS_URL, params={"symbol": symbol})
    r.raise_for_status()
    d = r.json()
    return {"sector": d.get("sector") or None, "industry": d.get("industry") or None,
            "currency": d.get("currency_code") or None}


def ingest_metadata(con, symbols: list[str], log=print) -> int:
    headers = {"User-Agent": USER_AGENT, "Referer": f"{BVB_BASE}/"}
    n = 0
    with httpx.Client(headers=headers, timeout=60) as client:
        for symbol in symbols:
            try:
                m = fetch_metadata(client, symbol)
            except httpx.HTTPError as e:
                log(f"{symbol}: eroare {e!r}")
                continue
            con.execute("UPDATE instruments SET sector = ?, industry = ?, currency = ? WHERE symbol = ?",
                        [m["sector"], m["industry"], m["currency"], symbol])
            n += 1
            time.sleep(REQUEST_DELAY / 2)
    return n


def last_complete_day(now: datetime | None = None) -> date:
    """Ultima zi a carei bara e finala: azi dupa 18:30, altfel ieri."""
    now = (now or datetime.now(TZ)).astimezone(TZ)
    today = now.date()
    if (now.hour, now.minute) >= SESSION_END:
        return today
    return date.fromordinal(today.toordinal() - 1)


def parse(symbol: str, raw: dict, adj: dict | None, until: date) -> list[list]:
    """-> randuri pentru prices_eod (date, symbol, source, open, high, low, close, volume, adj_close)."""
    if raw.get("s") != "ok" or not raw.get("t"):
        return []
    adj_by_ts = {}
    if adj and adj.get("s") == "ok":
        adj_by_ts = dict(zip(adj["t"], adj["c"]))
    rows = []
    for i, ts in enumerate(raw["t"]):
        day = datetime.fromtimestamp(ts, tz=timezone.utc).date()
        close = raw["c"][i]
        if day > until or close is None:
            continue
        volume = raw["v"][i]
        rows.append([
            day, symbol, SOURCE, raw["o"][i], raw["h"][i], raw["l"][i], close,
            int(volume) if volume is not None else None, adj_by_ts.get(ts),
        ])
    return rows


def store(con, rows: list[list]) -> int:
    if rows:
        con.executemany(
            """
            INSERT OR REPLACE INTO prices_eod
                (date, symbol, source, open, high, low, close, volume, adj_close)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    return len(rows)


def ingest(con, symbols: list[str], log=print) -> dict[str, int]:
    until = last_complete_day()
    counts = {}
    headers = {"User-Agent": USER_AGENT, "Referer": f"{BVB_BASE}/"}
    with httpx.Client(headers=headers, timeout=60) as client:
        for symbol in symbols:
            try:
                raw = fetch(client, symbol, adjusted=False)
                time.sleep(REQUEST_DELAY / 2)
                adj = fetch(client, symbol, adjusted=True)
            except httpx.HTTPError as e:
                log(f"{symbol}: eroare {e!r}")
                counts[symbol] = 0
                continue
            rows = parse(symbol, raw, adj, until)
            counts[symbol] = store(con, rows)
            log(f"{symbol}: {counts[symbol]} zile" + (f" ({rows[0][0]} - {rows[-1][0]})" if rows else ""))
            time.sleep(REQUEST_DELAY)
    return counts
