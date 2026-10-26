# Surse de date — fezabilitate (verificat 2026-10-26)

## BVB (bvb.ro)

`curl` simplu dă timeout pe bvb.ro (TLS/anti-bot); în browser paginile merg. Site ASP.NET WebForms (`__VIEWSTATE`, postback-uri).

| Date | URL | Format | Observații |
|---|---|---|---|
| Sumar zilnic toate simbolurile (OHLC, mediu, închidere, preț ref., volum, valoare, nr. tranz.) | `/TradingAndStatistics/Trading/HistoricalTradingInfo` | tabel DataTables, navigare cu „<” / „>” | ~150–360 simboluri/zi. **Doar ultimele 30 de zile.** Sursă principală pentru EOD incremental (`bvb ingest bvb`). |
| Istoric per simbol (ultimele 10 ședințe) | `/FinancialInstruments/Details/FinancialInstrumentsDetails.aspx?s=TLV` → tab Tranzactionare | HTML (`gvSummar`) | Istoric scurt. |
| Istoric complet per simbol (grafic) | `wapi.bvb.ro/api/history?symbol=…&rs=1D&ajust=0/1` (TradingView UDF) | JSON | API intern al graficului, nedocumentat. Istoric complet (TLV din 1997), brut (`ajust=0`) și ajustat (`ajust=1`); merge și din curl. Folosit pentru istoric (`bvb ingest history`) cu acordul utilizatorului, uz personal. |
| Metadate simbol (sector, industrie, sesiune) | `wapi.bvb.ro/api/symbols?symbol=TLV` | JSON | Idem. |
| Rapoarte curente (AGA, art. 19 MAR, răscumpărări etc.) | `/FinancialInstruments/SelectedData/CurrentReports` | tabel + link PDF (`/infocont/...`, `/info/Raportari/...`) | Filtre tip/subtip. Fără RSS. Conținutul e PDF. |
| Rezultate financiare (anuale, trimestriale) | `/FinancialInstruments/SelectedData/FinancialResults` | tabel + PDF/ZIP (`/Raportari/<an>/...`) | Extragere din PDF = partea grea. |
| Calendar financiar | `/FinancialInstruments/SelectedData/FinancialCalendar` | HTML | Date publicare rezultate, AGA etc. |
| Dividende | `/FinancialInstruments/CorporateActions/InfoDividend` | tabel | Dividend, DIVY, ex-date, dată înregistrare, plată, total. Necesar pentru ajustarea prețurilor. |
| Modificări capital social | `/FinancialInstruments/CorporateActions/...` (meniu „Modificari capital social”) | tabel | Pentru splituri/majorări. |
| Indicatori, acționari raportați, AGA | `/FinancialInstruments/SelectedData/{Indicators,ReportedShareholders,GMSCalendar}` | HTML | |

**Termeni de utilizare** (`/Disclaimer.aspx`): drept doar de vizualizare și copie pentru uz personal, necomercial. Copierea, stocarea sau redistribuirea către terți cer acordul scris al BVB. Alternativă: „Servicii → Vanzare date → Pentru investitori”.

## Alte surse

| Sursă | Endpoint | Stare | Note |
|---|---|---|---|
| Yahoo Finance | `query1.finance.yahoo.com/v8/finance/chart/TLV.RO?period1=…&interval=1d&events=div,split` | ⚠️ JSON | TLV: 4847 zile din 2007-12, include dividende/splituri. Neoficial; pe 2026-10-26 a răspuns 429 la colectarea automată. Doar pentru validare. |
| Stooq | `stooq.com/q/d/l/?s=tlv.ro&i=d` | ❌ | Verificare JS anti-bot. |
| filings.xbrl.org (ESEF) | `filings.xbrl.org/api/filings?filter[country]=RO` | ✅ JSON:API | 115 rapoarte RO, cu xBRL-JSON (`json_url`). Date financiare structurate, doar rapoarte anuale. |
| data.gov.ro — situații financiare | CKAN `package_search`, seturi `situatii_financiare_2008…2025` | ✅ | Bilanțuri anuale pentru toate firmele (inclusiv necotate). |
| BNR curs valutar | `curs.bnr.ro/nbrfxrates.xml` (vechiul `bnr.ro/nbrfxrates.xml` → HTML) | ✅ XML | De verificat URL-ul arhivei anuale pe noul domeniu. |
| Eurostat | `ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/...` | ✅ JSON | HICP, PIB etc. |
| GLEIF | `api.gleif.org/api/v1/lei-records` | ✅ JSON | LEI → legătură cu filings.xbrl.org. |
| ASF | `asfromania.ro` | ✅ HTML | Fără API. |
| Știri RSS | `zf.ro/rss`, `profit.ro/rss` | ✅ RSS | |

## Neverificat încă
- Ce conține exportul CSV din Sumare tranzacționare și cât de departe în trecut merge selectorul de dată.
- BVB Research Hub, portofolii fonduri de pensii Pilon II, INS TEMPO, Depozitarul Central.
