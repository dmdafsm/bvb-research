"""Sumarul zilnic de tranzactionare BVB (toate actiunile, o sedinta pe pagina).

Pagina publica: /TradingAndStatistics/Trading/HistoricalTradingInfo
- arata implicit ultima sedinta incheiata;
- permite navigarea cu butoanele "<" / ">" doar in ultimele ~30 de zile;
- tabelul e randat cu DataTables (paginare in browser), deci luam randurile
  din API-ul DataTables din pagina, nu din DOM-ul vizibil.
"""

import time
from collections.abc import Iterator
from datetime import date, datetime

from selectolax.lexbor import LexborHTMLParser

from bvb.config import BVB_BASE, RAW_DIR, REQUEST_DELAY, USER_AGENT

URL = f"{BVB_BASE}/TradingAndStatistics/Trading/HistoricalTradingInfo"

COLUMNS = {
    "Simbol": "symbol",
    "Piata": "market",
    "Nr. tranz.": "trades",
    "Volum": "volume",
    "Valoare": "value",
    "Desch.": "open",
    "Min.": "low",
    "Max.": "high",
    "Mediu": "avg_price",
    "Inchidere": "close",
    "Pret ref.": "ref_price",
    "Var. (%)": "change_pct",
}
INT_FIELDS = {"trades", "volume"}
TEXT_FIELDS = {"symbol", "market"}

TABLE_JS = """() => {
    const t = document.querySelector('#gv');
    if (!t) return '';
    const head = t.querySelector('thead').outerHTML;
    const rows = (window.jQuery && jQuery.fn.dataTable && jQuery.fn.dataTable.isDataTable(t))
        ? jQuery(t).DataTable().rows().nodes().toArray()
        : [...t.querySelectorAll('tbody tr')];
    return '<table id="gv">' + head + '<tbody>' + rows.map(r => r.outerHTML).join('') + '</tbody></table>';
}"""


def parse_number(text: str) -> float | None:
    """'12.345.678,90' -> 12345678.9"""
    text = text.strip().replace("\xa0", "")
    if not text or text == "-":
        return None
    return float(text.replace(".", "").replace(",", "."))


def parse_summary(html: str) -> list[dict]:
    tree = LexborHTMLParser(html)
    table = tree.css_first("table#gv")
    if table is None:
        return []
    headers = [th.text(strip=True) for th in table.css("thead th")]
    fields = [COLUMNS.get(h) for h in headers]
    missing = set(COLUMNS.values()) - set(fields)
    if missing:
        raise ValueError(f"Coloane lipsa in sumarul BVB: {sorted(missing)}")

    rows = []
    for tr in table.css("tbody tr"):
        cells = tr.css("td")
        if len(cells) < len(fields):
            continue  # rand "nu exista date"
        row = {}
        for field, td in zip(fields, cells, strict=False):  # randurile pot avea celule in plus
            if field is None:
                continue
            text = td.text(strip=True)
            if field in TEXT_FIELDS:
                row[field] = text
            else:
                num = parse_number(text)
                row[field] = int(num) if field in INT_FIELDS and num is not None else num
        rows.append(row)
    return rows


def fetch_sessions(
    max_sessions: int, known: set[date] = frozenset(), walk_known: bool = False
) -> Iterator[tuple[date, str]]:
    """Merge inapoi de la ultima sedinta; produce (data, html_tabel) pentru fiecare zi noua.

    La prima data din `known` (deja in baza) se opreste, sau, cu `walk_known`,
    o sare si continua (pentru umplerea golurilor). Se opreste si dupa
    `max_sessions` pasi sau cand pagina nu mai permite mersul inapoi.
    """
    from playwright.sync_api import TimeoutError as PwTimeout
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT, locale="ro-RO")
        page.goto(URL, wait_until="networkidle", timeout=60_000)
        try:
            for _ in range(max_sessions):
                current = page.input_value("#txtDateI")
                day = datetime.strptime(current, "%d.%m.%Y").date()
                if day in known:
                    if not walk_known:
                        return
                else:
                    yield day, page.evaluate(TABLE_JS)

                if page.is_disabled("#lbleft"):
                    return  # limita de ~30 zile atinsa
                page.click("#lbleft")
                try:
                    page.wait_for_function(
                        "prev => document.querySelector('#txtDateI').value !== prev",
                        arg=current,
                        timeout=30_000,
                    )
                except PwTimeout:
                    return  # limita de ~30 zile atinsa
                page.wait_for_load_state("networkidle")
                time.sleep(REQUEST_DELAY)
        finally:
            browser.close()


def save_raw(day: date, html: str) -> None:
    out = RAW_DIR / "bvb_summary" / f"{day.isoformat()}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")


def store(con, day: date, rows: list[dict]) -> int:
    if not rows:
        return 0
    con.executemany(
        """
        INSERT OR REPLACE INTO prices_eod
            (date, symbol, source, market, open, high, low, close, avg_price,
             ref_price, change_pct, volume, value, trades)
        VALUES (?, ?, 'bvb', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            [
                day,
                r["symbol"],
                r["market"],
                r["open"],
                r["high"],
                r["low"],
                r["close"],
                r["avg_price"],
                r["ref_price"],
                r["change_pct"],
                r["volume"],
                r["value"],
                r["trades"],
            ]
            for r in rows
        ],
    )
    con.executemany(
        """
        INSERT INTO instruments (symbol, market, first_seen, last_seen) VALUES (?, ?, ?, ?)
        ON CONFLICT (symbol) DO UPDATE SET
            market = excluded.market,
            first_seen = least(instruments.first_seen, excluded.first_seen),
            last_seen = greatest(instruments.last_seen, excluded.last_seen)
        """,
        [[r["symbol"], r["market"], day, day] for r in rows],
    )
    return len(rows)
