"""Actiuni delistate (pentru backtest-uri fara bias de supravietuire).

Lista: cautarea avansata de pe bvb.ro (/FinancialInstruments/Markets/AdvancedSearch),
tip "Actiuni", cu "Include instrumentele delistate"; tabelul e paginat pe server,
asa ca parcurgem paginile cu butonul "Inainte". Cele mai multe intrari sunt
fostele societati RASDAQ, fara istoric pe BVB; istoricul il cautam apoi cu
API-ul graficului (`bvb_history`), iar simbolurile fara date sunt marcate.
"""

import json
import time

from bvb.config import BVB_BASE, RAW_DIR, REQUEST_DELAY, USER_AGENT

URL = f"{BVB_BASE}/FinancialInstruments/Markets/AdvancedSearch"
LIST_PATH = RAW_DIR / "delisted" / "shares.json"
FIELDS = ["symbol", "isin", "name", "type", "status", "issuer", "country", "county", "city", "cui"]

ROWS_JS = """() => [...document.querySelectorAll('#gv tbody tr')].map(tr => {
    const td = [...tr.cells];
    if (td.length < 9) return null;
    const sym = td[0].querySelector('a');
    const isin = td[0].querySelector('p');
    return [sym ? sym.textContent.trim() : td[0].textContent.trim(), isin ? isin.textContent.trim() : '',
            ...td.slice(1, 9).map(c => c.textContent.trim())];
}).filter(Boolean)"""


def fetch_list(log=print) -> list[dict]:
    from playwright.sync_api import sync_playwright

    rows: dict[str, dict] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT, locale="ro-RO")
        try:
            page.goto(URL, wait_until="networkidle", timeout=60_000)
            box = "#ctl00_ctl00_body_rightColumnPlaceHolder_state"
            if not page.is_checked(box):
                page.click(box)
                page.wait_for_load_state("networkidle")
            page.click("input[type=submit][value^='Actiuni']")
            page.wait_for_selector("#gv tbody tr", timeout=60_000)
            page.wait_for_load_state("networkidle")
            page.select_option("select[name=gv_length]", "20", force=True)
            page.wait_for_load_state("networkidle")
            n_page = 0
            while True:
                for r in page.evaluate(ROWS_JS):
                    rows[r[0]] = dict(zip(FIELDS, r, strict=True))
                n_page += 1
                if n_page % 25 == 0:
                    log(f"pagina {n_page}: {len(rows)} simboluri")
                nxt = page.locator("#gv_next")
                if nxt.count() == 0 or "disabled" in (nxt.get_attribute("class") or ""):
                    break
                first = page.evaluate("() => document.querySelector('#gv tbody tr')?.innerText || ''")
                nxt.click()
                page.wait_for_function(
                    "prev => (document.querySelector('#gv tbody tr')?.innerText || '') !== prev",
                    arg=first,
                    timeout=60_000,
                )
                time.sleep(REQUEST_DELAY / 2)
        finally:
            browser.close()
    out = list(rows.values())
    LIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    LIST_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")
    return out


def load_list() -> list[dict]:
    return json.loads(LIST_PATH.read_text(encoding="utf-8")) if LIST_PATH.exists() else []
