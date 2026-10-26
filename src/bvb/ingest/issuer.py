"""Fisa emitentului de pe bvb.ro: date de baza, dividende, modificari de capital.

Pagina: /FinancialInstruments/Details/FinancialInstrumentsDetails.aspx?s=<SIMBOL>
- tab "Sumar": ISIN, segment, categorie, numar actiuni, valoare nominala;
- tab "Emitent": profil (CUI, domeniu), istoric dividende (`gvDividend`),
  modificari capital social (`gvMCapSoc`).
Tab-urile sunt postback-uri ASP.NET, deci le apasam in browser si salvam
tabelele (cu toate randurile DataTables) intr-un singur HTML, parsat separat.
"""

import time
from datetime import date, datetime

from selectolax.lexbor import LexborHTMLParser

from bvb.config import BVB_BASE, RAW_DIR, REQUEST_DELAY, USER_AGENT
from bvb.ingest.bvb_summary import parse_number

URL = f"{BVB_BASE}/FinancialInstruments/Details/FinancialInstrumentsDetails.aspx?s={{symbol}}"

SNAPSHOT_JS = """() => {
    const out = [];
    for (const t of document.querySelectorAll('table')) {
        if (t.closest('#gvLast, #gvMMOrderBook')) continue;
        if (window.jQuery && jQuery.fn.dataTable && jQuery.fn.dataTable.isDataTable(t)) {
            const head = t.tHead ? t.tHead.outerHTML : '';
            const rows = jQuery(t).DataTable().rows().nodes().toArray().map(r => r.outerHTML).join('');
            out.push(`<table id="${t.id}" class="${t.className}">${head}<tbody>${rows}</tbody></table>`);
        } else {
            out.push(t.outerHTML);
        }
    }
    return out.join('\\n');
}"""


def fetch_snapshots(symbols: list[str]):
    """Pentru fiecare simbol: (simbol, html cu tabelele din tab-urile Sumar si Emitent)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT, locale="ro-RO")
        try:
            for symbol in symbols:
                try:
                    page.goto(URL.format(symbol=symbol), wait_until="networkidle", timeout=60_000)
                    summary = page.evaluate(SNAPSHOT_JS)
                    page.click("input[type=submit][value='Emitent']")
                    page.wait_for_selector("#ctl00_body_ctl02_CompanyProfile_dvIssProfile", timeout=30_000)
                    page.wait_for_load_state("networkidle")
                    issuer = page.evaluate(SNAPSHOT_JS)
                except Exception as e:  # o fisa lipsa nu opreste restul
                    yield symbol, None, e
                    continue
                yield symbol, f"<html><body>\n{summary}\n<hr id='emitent'>\n{issuer}\n</body></html>", None
                time.sleep(REQUEST_DELAY)
        finally:
            browser.close()


def save_raw(symbol: str, html: str) -> None:
    out = RAW_DIR / "issuer" / f"{symbol}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")


KV_TABLES = ("dvInfo", "dvIssProfile", "dvIndicators")


def _date(text: str) -> date | None:
    text = text.strip()
    return datetime.strptime(text, "%d.%m.%Y").date() if text else None


def _kv(table) -> dict[str, str]:
    """Tabele cheie/valoare cu 2 celule pe rand."""
    out = {}
    for tr in table.css("tr"):
        cells = tr.css("td")
        if len(cells) >= 2:
            out[cells[0].text(strip=True).rstrip(":").strip()] = cells[1].text(strip=True)
    return out


def _rows(tree, table_id: str) -> list[list[str]]:
    table = tree.css_first(f"table#{table_id}")
    if table is None:
        return []
    return [[td.text(strip=True) for td in tr.css("td")] for tr in table.css("tbody tr")]


def parse(symbol: str, html: str) -> dict:
    tree = LexborHTMLParser(html)
    info = {}
    for table in tree.css("table"):
        table_id = table.attributes.get("id") or ""
        if not table_id or table_id.endswith(KV_TABLES):
            info.update(_kv(table))

    name = None
    ca = tree.css_first("table[id$='dvIssCA']")
    if ca is not None:
        first = ca.css_first("tr")
        name = first.text(strip=True) if first else None

    shares = info.get("Numar total actiuni")
    nominal = info.get("Valoare Nominala")
    listing = info.get("Data start tranzactionare")
    instrument = {
        "symbol": symbol,
        "name": name,
        "isin": info.get("ISIN"),
        "segment": info.get("Segment"),
        "category": info.get("Categorie"),
        "status": info.get("Stare"),
        "cui": info.get("Cod Fiscal / CUI"),
        "activity": info.get("Domeniu de activitate"),
        "website": info.get("Website"),
        "shares": int(parse_number(shares)) if shares else None,
        "nominal_value": parse_number(nominal) if nominal else None,
        "listing_date": _date(listing) if listing else None,
    }

    dividends = []
    for cells in _rows(tree, "gvDividend"):
        if len(cells) < 7 or not cells[1]:
            continue
        dividends.append({
            "symbol": symbol,
            "fiscal_year": int(cells[0]) if cells[0].isdigit() else None,
            "amount": parse_number(cells[1]),
            "agm_date": _date(cells[2]),
            "record_date": _date(cells[3]),
            "ex_date": _date(cells[4]),
            "declared_date": _date(cells[5]),
            "pay_date": _date(cells[6]),
        })

    capital = []
    for cells in _rows(tree, "gvMCapSoc"):
        if len(cells) < 9:
            continue
        capital.append({
            "symbol": symbol,
            "change_date": _date(cells[0]),
            "agm_date": _date(cells[1]),
            "ref_date": _date(cells[2]),
            "record_date": _date(cells[3]),
            "operation": cells[4],
            "shares_before": int(parse_number(cells[5])) if cells[5] else None,
            "shares_after": int(parse_number(cells[6])) if cells[6] else None,
            "nominal_before": parse_number(cells[7]) if cells[7] else None,
            "nominal_after": parse_number(cells[8]) if cells[8] else None,
        })
    return {"instrument": instrument, "dividends": dividends, "capital": capital}


INSTRUMENT_FIELDS = ["name", "isin", "segment", "category", "status", "cui", "activity", "website",
                     "shares", "nominal_value", "listing_date"]
DIVIDEND_FIELDS = ["symbol", "fiscal_year", "amount", "agm_date", "record_date", "ex_date", "declared_date", "pay_date"]
CAPITAL_FIELDS = ["symbol", "change_date", "agm_date", "ref_date", "record_date", "operation",
                  "shares_before", "shares_after", "nominal_before", "nominal_after"]


def store(con, data: dict) -> None:
    inst = data["instrument"]
    symbol = inst["symbol"]
    con.execute(
        f"UPDATE instruments SET {', '.join(f'{f} = ?' for f in INSTRUMENT_FIELDS)}, issuer_updated = now() "
        "WHERE symbol = ?",
        [inst[f] for f in INSTRUMENT_FIELDS] + [symbol],
    )
    # Tabelele de pe fisa sunt istoricul complet: le inlocuim integral.
    con.execute("DELETE FROM dividends WHERE symbol = ?", [symbol])
    con.execute("DELETE FROM capital_changes WHERE symbol = ?", [symbol])
    if data["dividends"]:
        con.executemany(
            f"INSERT INTO dividends ({', '.join(DIVIDEND_FIELDS)}) VALUES ({', '.join('?' * len(DIVIDEND_FIELDS))})",
            [[d[f] for f in DIVIDEND_FIELDS] for d in data["dividends"]],
        )
    if data["capital"]:
        con.executemany(
            f"INSERT INTO capital_changes ({', '.join(CAPITAL_FIELDS)}) VALUES ({', '.join('?' * len(CAPITAL_FIELDS))})",
            [[c[f] for f in CAPITAL_FIELDS] for c in data["capital"]],
        )
