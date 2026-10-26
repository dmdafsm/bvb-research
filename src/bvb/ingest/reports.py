"""Rapoarte curente (anunturi) si calendarul emitentilor de pe bvb.ro.

Surse:
- pagina globala /FinancialInstruments/SelectedData/CurrentReports: fereastra de
  ~10 zile pana la data selectata, toti emitentii; includem si tranzactiile
  persoanelor cu atributii de conducere (art. 19 MAR), excluse implicit;
- tab-ul "Stiri" din fisa emitentului: ultimul an pentru un emitent (backfill);
- calendarul financiar si AGA din tab-ul "Sumar" al fisei (salvat de `issuer`).
"""

import re
import time
from datetime import date, datetime

from selectolax.lexbor import LexborHTMLParser

from bvb.config import BVB_BASE, RAW_DIR, REQUEST_DELAY, USER_AGENT

GLOBAL_URL = f"{BVB_BASE}/FinancialInstruments/SelectedData/CurrentReports"

# Categorii deduse din titlu (prima potrivire castiga).
CATEGORIES = [
    ("insider", r"art\.? ?19|tranzac\w* (management|persoan|pdmr)|persoane cu (functii|responsabilitati)"),
    ("buyback", r"rascumpar|actiuni proprii"),
    ("dividend", r"dividend"),
    (
        "results",
        r"rezultat\w* financiar|raport\w* (trimestrial|semestrial|anual)|situatii\w* financiare|"
        r"\b(t|q)[1-4]\b|trimestrul|semestrul|preliminar",
    ),
    ("agm", r"\bag[aoe]{1,2}a?\b|adunar\w* general|convoca\w*|hotarar\w* (ag|adunar)"),
    ("calendar", r"calendar financiar"),
    ("holdings", r"detiner|prag\w* de|notificare privind (actionar|drepturi de vot)|drepturi de vot"),
    ("related_party", r"art\.? ?(108|234)|parti afiliate|tranzactii cu parti"),
    ("management", r"conducer|director|consiliu\w* de (administratie|supraveghere)|directorat|demisi|numire|revocare"),
    ("contract", r"contract|achizit|licitat|investiti"),
    ("rating", r"rating"),
    ("nav", r"\bvan\b|valoarea activului net|\bnav\b"),
    ("legal", r"litigi|consiliul concurentei|instant|dosar|sentint"),
    ("shareholders", r"structura (de )?actionariat"),
    ("trading", r"suspendare|reluare|tranzactionar"),
    ("capital", r"majorare|reducere a capital|capital social|drept\w* de preferinta|oferta"),
]

MONTHS = {
    "ianuarie": 1,
    "februarie": 2,
    "martie": 3,
    "aprilie": 4,
    "mai": 5,
    "iunie": 6,
    "iulie": 7,
    "august": 8,
    "septembrie": 9,
    "octombrie": 10,
    "noiembrie": 11,
    "decembrie": 12,
}


def classify(title: str) -> str:
    t = title.lower()
    for name, pattern in CATEGORIES:
        if re.search(pattern, t):
            return name
    return "other"


def _dt(text: str) -> datetime | None:
    text = " ".join(text.split())
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _links(node) -> list[str]:
    out = []
    for a in node.css("a[href]"):
        href = a.attributes.get("href") or ""
        if ".pdf" in href.lower() or "/infocont/" in href or "/info/" in href:
            out.append(href if href.startswith("http") else BVB_BASE + href)
    return out


def parse_global(html: str) -> list[dict]:
    """Tabelul `gvv` (toate randurile DataTables): simbol, titlu, data, tip, PDF-uri."""
    tree = LexborHTMLParser(html)
    rows = []
    for tr in tree.css("table#gvv tbody tr"):
        td = tr.css("td")
        if len(td) < 6:
            continue
        sym = td[0].css_first("a")
        btn = td[2].css_first("input")
        title = (btn.attributes.get("value") if btn else td[2].text(strip=True)) or ""
        rows.append(
            {
                "symbol": sym.text(strip=True) if sym else td[0].text(strip=True).split()[0],
                "published": _dt(td[3].text(strip=True)),
                "title": title.strip(),
                "bvb_type": td[4].text(strip=True),
                "links": _links(td[5]),
            }
        )
    return rows


def parse_issuer_news(symbol: str, html: str) -> list[dict]:
    """Tabelul `gv` din tab-ul Stiri al fisei emitentului."""
    tree = LexborHTMLParser(html)
    rows = []
    for tr in tree.css("table#gv tbody tr"):
        btn = tr.css_first("input[type=submit]")
        when = tr.css_first("p.date")
        if not btn or not when:
            continue
        rows.append(
            {
                "symbol": symbol,
                "published": _dt(when.text(strip=True)),
                "title": (btn.attributes.get("value") or "").strip(),
                "bvb_type": None,
                "links": _links(tr),
            }
        )
    return rows


def parse_ro_date(text: str) -> date | None:
    """'29 octombrie 2026' -> date"""
    m = re.match(r"\s*(\d{1,2})\s+([a-z]+)\s+(\d{4})", text.lower())
    if not m or m.group(2) not in MONTHS:
        return None
    return date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)))


def parse_calendar(symbol: str, html: str) -> list[dict]:
    """Calendarul financiar (`gvCF`) si AGA (`gvAGA`) din fisa salvata a emitentului."""
    tree = LexborHTMLParser(html)
    out = []
    for table_id, kind in (("gvCF", "financial"), ("gvAGA", "agm")):
        for tr in tree.css(f"table#{table_id} tr"):
            cells = [td.text(strip=True) for td in tr.css("td")]
            text = " ".join(c for c in cells if c)
            d = parse_ro_date(text)
            if d is None:
                continue
            event = re.sub(r"^\s*\d{1,2}\s+[a-z]+\s+\d{4}\s*", "", text, flags=re.I).strip()
            out.append({"symbol": symbol, "date": d, "kind": kind, "event": event})
    # aceeasi intrare apare uneori de doua ori (tab-urile Sumar si Emitent)
    return list({(e["date"], e["kind"], e["event"]): e for e in out}.values())


def fetch_global(windows: int = 1, include_insiders: bool = True):
    """Paginile globale: (data selectata, html). Fiecare fereastra acopera ~10 zile
    calendaristice pana la data selectata; butonul "<" trece la fereastra anterioara."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT, locale="ro-RO")
        page.goto(GLOBAL_URL, wait_until="networkidle", timeout=60_000)
        try:
            if include_insiders and page.is_checked("#chOutInsiders"):
                page.click("#chOutInsiders")
                page.wait_for_load_state("networkidle")
            for step in range(windows):
                if step:
                    if page.is_disabled("#lbleft"):
                        return
                    current = page.input_value("#txtDateI")
                    page.click("#lbleft")
                    page.wait_for_function(
                        "prev => document.querySelector('#txtDateI').value !== prev", arg=current, timeout=30_000
                    )
                    page.wait_for_load_state("networkidle")
                    time.sleep(REQUEST_DELAY)
                html = page.evaluate("""() => {
                    const t = document.querySelector('#gvv');
                    if (!t) return '';
                    const rows = jQuery(t).DataTable().rows().nodes().toArray().map(r => r.outerHTML).join('');
                    return '<table id="gvv"><tbody>' + rows + '</tbody></table>';
                }""")
                yield page.input_value("#txtDateI"), html
        finally:
            browser.close()


def save_raw(name: str, html: str) -> None:
    out = RAW_DIR / "reports" / f"{name}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")


def store_reports(con, rows: list[dict]) -> int:
    """Upsert pe (simbol, minut, titlu).

    Pagina globala da ora la minut, tab-ul Stiri al emitentului si secundele;
    taiem la minut ca acelasi raport din ambele surse sa fie un singur rand.
    """
    n = 0
    for r in rows:
        if not r["published"] or not r["title"]:
            continue
        con.execute(
            """INSERT INTO reports (symbol, published, title, category, bvb_type, url_ro, url_en)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (symbol, published, title) DO UPDATE SET
                   category = excluded.category,
                   bvb_type = coalesce(excluded.bvb_type, reports.bvb_type),
                   url_ro = coalesce(excluded.url_ro, reports.url_ro),
                   url_en = coalesce(excluded.url_en, reports.url_en)""",
            [
                r["symbol"],
                r["published"].replace(second=0, microsecond=0),
                r["title"],
                classify(r["title"]),
                r["bvb_type"],
                r["links"][0] if r["links"] else None,
                r["links"][1] if len(r["links"]) > 1 else None,
            ],
        )
        n += 1
    return n


def normalize(con) -> int:
    """Uneste randurile aceluiasi raport salvat cu si fara secunde si reclasifica titlurile
    (categoriile se schimba cand se modifica CATEGORIES). Idempotent. -> randuri eliminate."""
    before = con.execute("SELECT count(*) FROM reports").fetchone()[0]
    con.execute("BEGIN")
    try:
        con.execute("""
            CREATE OR REPLACE TEMP TABLE reports_merged AS
            SELECT symbol, date_trunc('minute', published) AS published, title,
                   max(bvb_type) AS bvb_type, max(url_ro) AS url_ro, max(url_en) AS url_en, max(text) AS text
            FROM reports GROUP BY ALL
        """)
        con.execute("DELETE FROM reports")
        con.execute("""
            INSERT INTO reports (symbol, published, title, bvb_type, url_ro, url_en, text)
            SELECT symbol, published, title, bvb_type, url_ro, url_en, text FROM reports_merged
        """)
        con.execute("DROP TABLE reports_merged")
        titles = [t for (t,) in con.execute("SELECT DISTINCT title FROM reports").fetchall()]
        con.executemany("UPDATE reports SET category = ? WHERE title = ?", [[classify(t), t] for t in titles])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return before - con.execute("SELECT count(*) FROM reports").fetchone()[0]


def store_calendar(con, symbol: str, events: list[dict]) -> None:
    con.execute("DELETE FROM calendar WHERE symbol = ?", [symbol])
    if events:
        con.executemany(
            "INSERT INTO calendar (symbol, date, kind, event) VALUES (?, ?, ?, ?)",
            [[e["symbol"], e["date"], e["kind"], e["event"]] for e in events],
        )
