from datetime import date, datetime
from pathlib import Path

from bvb.ingest import news, reports

FIXTURES = Path(__file__).parent / "fixtures"

GLOBAL_ROW = """<table id="gvv"><tbody><tr class="odd"> <td> <span><a href="/FinancialInstruments/Details/FinancialInstrumentsDetails.aspx?s=BVB"><b> BVB</b></a></span>&nbsp;<p style="font-size: 11px">ROBVBAACNOR0</p> </td><td>BURSA DE VALORI BUCURESTI SA</td><td data-search="x"><input type="submit" name="n" value="Notificare - rascumparare actiuni proprii 19.10-23.10.2026" id="b" class="mLnkbttS"></td><td class="text-right">26.10.2026 15:48</td><td align="right">Altele</td><td align="right"> <a class="aLinks" href="/infocont/infocont26/BVB_RO.pdf">1</a> <a class="aLinks" href="/infocont/infocont26/BVB_EN.pdf">2</a> </td> </tr></tbody></table>"""

NEWS_ROW = """<table id="gv"><tbody><tr tabindex="1" class="odd"> <td> <div> <div> <input type="submit" name="n" value="Calendar financiar 2027" class="mLnkbttS"> <p class="date">22.10.2026 16:00:16</p> </div> </div> <div> <a href="https://bvb.ro/infocont/infocont26/SNP_Calendar.pdf"><i></i></a> </div> </td></tr></tbody></table>"""


def test_parse_global_row():
    [r] = reports.parse_global(GLOBAL_ROW)
    assert r["symbol"] == "BVB"
    assert r["published"] == datetime(2026, 10, 26, 15, 48)
    assert r["title"].startswith("Notificare - rascumparare")
    assert r["links"] == [
        "https://bvb.ro/infocont/infocont26/BVB_RO.pdf",
        "https://bvb.ro/infocont/infocont26/BVB_EN.pdf",
    ]
    assert reports.classify(r["title"]) == "buyback"


def test_parse_issuer_news_row():
    [r] = reports.parse_issuer_news("SNP", NEWS_ROW)
    assert (r["symbol"], r["published"], r["title"]) == (
        "SNP",
        datetime(2026, 10, 22, 16, 0, 16),
        "Calendar financiar 2027",
    )
    assert r["links"] == ["https://bvb.ro/infocont/infocont26/SNP_Calendar.pdf"]


def test_classify():
    assert reports.classify("Tranzactii management - art. 19 Reg. (UE) 596/2014") == "insider"
    assert reports.classify("Rezultate financiare trimestrul III 2026") == "results"
    assert reports.classify("Convocare AGOA 28.04.2026") == "agm"
    assert reports.classify("Plata dividende aferente exercitiului 2025") == "dividend"
    assert reports.classify("Notificare detineri peste pragul de 5%") == "holdings"
    assert reports.classify("VAN la data 30.09.2026") == "nav"
    assert reports.classify("Informare - decizie Consiliul Concurentei") == "legal"
    assert reports.classify("Ceva fara categorie") == "other"


def test_calendar_from_issuer_fixture():
    assert reports.parse_ro_date("29 octombrie 2026 Rezultate") == date(2026, 10, 29)
    events = reports.parse_calendar("SNP", (FIXTURES / "issuer_SNP.html").read_text())
    kinds = {e["kind"] for e in events}
    assert kinds == {"financial", "agm"}
    assert any(e["date"] == date(2026, 10, 29) and "trimestrul III" in e["event"] for e in events)


def test_news_matcher_and_feed():
    match = news.build_matcher(
        [
            ("SNP", "OMV PETROM S.A."),
            ("TLV", "BANCA TRANSILVANIA S.A."),
            ("M", "MED LIFE S.A."),
            ("EL", "SOCIETATEA ENERGETICA ELECTRICA S.A."),
        ]
    )
    assert match("Profitul OMV Petrom a scazut; Banca Transilvania creste") == ["SNP", "TLV"]
    assert match("MedLife cumpara o clinica") == ["M"]
    assert match("Pretul electricitatii") == []  # fara potriviri partiale
    xml = b"""<rss><channel><item><title>Petrom investeste</title><link>https://x/1</link>
              <description>&lt;p&gt;Text&lt;/p&gt;</description><pubDate>Mon, 26 Oct 2026 10:00:00 +0200</pubDate></item>
              </channel></rss>"""
    [it] = news.parse_feed("zf", xml)
    assert (it["title"], it["url"], it["summary"]) == ("Petrom investeste", "https://x/1", "Text")
    assert it["published"] == datetime(2026, 10, 26, 10, 0)


def test_alerts_new_reports_once_and_exdividend(tmp_path):
    from bvb import alerts, db

    con = db.connect(tmp_path / "a.duckdb")
    con.execute("INSERT INTO watchlist (symbol) VALUES ('AAA')")
    con.execute(
        "INSERT INTO reports (symbol, published, title, category) VALUES "
        "('AAA', now() - INTERVAL 1 HOUR, 'Rezultate T3', 'results'), ('BBB', now(), 'x', 'other')"
    )
    con.execute("INSERT INTO dividends (symbol, amount, ex_date) VALUES ('AAA', 0.5, current_date + 3)")
    first = alerts.collect(con)
    assert any("[anunt] AAA" in line for line in first) and not any("BBB" in line for line in first)
    assert any("[ex-dividend] AAA" in line for line in first)
    second = alerts.collect(con)
    assert not any("[anunt]" in line for line in second)  # anuntul nu se repeta
