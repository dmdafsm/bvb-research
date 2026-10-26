# Plan — instrument de analiză BVB (uz personal)

Surse și fezabilitate: [surse-date.md](surse-date.md).

## Decizii implicite (de schimbat dacă e cazul)

| Subiect | Alegere | De ce |
|---|---|---|
| Limbaj | Python 3.12, `uv` | ecosistem pandas/numpy/scipy pentru analiză |
| Stocare | DuckDB (un fișier local) + PDF-uri pe disc | analitic, rapid, zero server |
| Colectare BVB | Playwright (Chromium headless) pe paginile publice | bvb.ro nu răspunde la clienți HTTP simpli; un browser real, rulat o dată pe zi, ritm lent |
| Interfață | Streamlit | dashboard local rapid; notebook-uri pentru explorare |
| Programare | containerul `ingest` din Docker Compose: zilnic la 19:15, sâmbăta rularea completă ([ADR 0004](engineering/decisions/0004-docker-compose.md)) | după închiderea pieței; independent de sistemul de operare |
| Monedă | RON; conversie EUR/USD prin BNR | |

Reguli de colectare: doar pagini publice, o rulare pe zi, pauze între cereri, cache local (nu se re-descarcă ce există deja), date doar pentru uz personal.

## Faza 0 — Fundație ✅
- Structura proiectului: `bvb/ingest`, `bvb/models`, `bvb/analytics`, `bvb/portfolio`, `app/`, `tests/`.
- Schema DuckDB: `instruments`, `prices_eod`, `corporate_actions`, `dividends`, `reports`, `calendar`, `fx_rates`, `fundamentals`, `ingest_log`.
- Config (cale DB, listă simboluri urmărite), logging, CLI (`bvb ingest prices --date …`).

## Faza 1 — Prețuri EOD ✅ (istoric din graficul BVB; sumarul BVB doar 30 de zile)
1. Scraper „Sumare tranzacționare”: pentru o dată → toate simbolurile (OHLC, mediu, închidere, preț ref., volum, valoare, nr. tranz.).
2. Verificare: cât de departe merge istoricul în trecut pe această pagină.
3. Backfill: zi cu zi pe BVB cât permite; pentru perioade mai vechi, Yahoo (`.RO`) ca sursă secundară, marcată în coloana `source`.
4. Reconciliere BVB vs Yahoo pe perioada comună (diferențe > prag → raport).
5. Indici (BET, BET-TR, BET-FI, BET-NG, BETPlus): valori zilnice pentru benchmark.
6. Job zilnic incremental + `ingest_log` (ce s-a descărcat, erori).

## Faza 2 — Metadate și acțiuni corporative ✅ (2026-10-26)
- Instrumente: simbol, ISIN, emitent, sector/industrie, piață (REGS/AeRO), număr acțiuni.
- Dividende (InfoDividend): ex-date, sumă, plată.
- Modificări capital social: splituri, consolidări, majorări cu drept de preferință.
- **Prețuri ajustate** calculate de noi (factor de ajustare cumulativ), validate cu Yahoo și cu BET vs BET-TR.

## Faza 3 — Anunțuri și calendar ✅
- Index rapoarte curente: simbol, dată, tip, titlu, link PDF; descărcare PDF pentru simbolurile urmărite.
- Clasificare pe categorii: AGA, dividende, art. 19 (tranzacții management), răscumpărări, contracte, rezultate.
- Calendar financiar + AGA → „ce urmează săptămâna asta” pentru portofoliu.
- Extragere text din PDF + căutare full-text; opțional rezumat cu Claude API.
- Feed RSS (ZF, Profit.ro) filtrat pe emitenți urmăriți.

## Faza 4 — Date fundamentale ✅ (data.gov.ro; rapoartele trimestriale PDF rămân neextrase)
1. ESEF (filings.xbrl.org, xBRL-JSON): rapoarte anuale structurate → venituri, profit net, active, capitaluri proprii, datorii, cash-flow operațional. Mapare LEI ↔ simbol prin GLEIF.
2. data.gov.ro: bilanțuri anuale pe CUI (inclusiv filiale necotate) ca sursă complementară.
3. Rapoarte trimestriale (PDF): extragere semi-automată (tabele + Claude API pentru structurare), cu validare manuală.
4. Indicatori derivați: P/E, P/BV, EV/EBITDA, ROE, ROA, marjă, datorie/capital, randament dividend, payout, creștere multi-an.

## Faza 5 — Analiză pe acțiune ✅ (multipli de evaluare în `bvb valuation` / `bvb fundamentals`)
- Randamente (simple/log), volatilitate (rolling), beta și corelație față de BET, drawdown maxim.
- **Lichiditate**: valoare medie zilnică tranzacționată, % zile fără tranzacții, spread estimat. Esențial pe BVB.
- Istoric dividende și evaluare (multipli față de propriul istoric și față de sector).
- Screener: filtre pe lichiditate, evaluare, randament dividend, calitate.

## Faza 6 — Risc ✅
- VaR / CVaR istoric și parametric (1 zi, 10 zile), stres pe scenarii istorice (2008, 2020, 2022).
- Matrice de corelație cu estimare robustă (shrinkage Ledoit-Wolf), având în vedere zilele fără tranzacții.
- Risc de concentrare (sector, emitent, stat ca acționar majoritar).
- Risc de lichiditate: câte zile durează lichidarea poziției la X% din volumul mediu.
- Risc valutar pentru instrumentele în EUR/USD.

## Faza 7 — Portofolii de test ✅ backtest (construcția optimizată și what-if rămân de făcut)
- Definire portofolii ipotetice (ponderi sau număr de acțiuni, dată start).
- Backtest cu reinvestire dividende, impozit pe dividende, comision broker, rebalansare periodică.
- Benchmark: BET-TR. Metrici: CAGR, volatilitate, Sharpe/Sortino (rata fără risc din titluri de stat/ROBOR), drawdown, tracking error.
- Construcție: ponderi egale, minimă varianță, risk parity, cu constrângeri de lichiditate.
- Analiză „what-if”: adaug/scot o poziție → impact asupra riscului.

## Faza 8 — Interfață ✅ (Streamlit + alerte; programarea automată prin Docker Compose)
- Streamlit: pagină emitent (grafic, fundamentale, dividende, anunțuri), screener, portofolii, risc, calendar.
- Alerte locale (în terminal sau log; notificare de sistem opțională pe macOS): anunț nou pentru un emitent urmărit, ex-dividend apropiat, mișcare > X%.

## Ordine recomandată și criterii de „gata”
| Pas | Gata când |
|---|---|
| 0 + 1 | DB cu prețuri EOD pentru toate simbolurile, backfill ≥ 5 ani, job zilnic funcțional |
| 2 | Prețuri ajustate validate (diferență față de Yahoo < 1% pe TLV, SNP, H2O, FP) |
| 5 + 7 (MVP) | Grafic + metrici risc pe acțiune și backtest pentru un portofoliu de test |
| 3 | Anunțuri noi pentru simbolurile urmărite în ≤ 1 zi |
| 4 | Fundamentale anuale ESEF pentru componenții BET |
| 6, 8 | Dashboard complet |

## Limitări cunoscute (după Faza 2)
- Lipsesc companiile delistate (istoric doar pentru simbolurile tranzacționate în ultimele 30 de zile) → bias de supraviețuire în backtest.
- 60 de salturi în factorul BVB fără modificare de capital asociată (`unknown`) sunt păstrate ca evenimente de capital.
- 125 de dividende fără dată ex/înregistrare utilizabilă sunt sărite.
- Dividendele sunt brute (fără impozit).

## Riscuri cunoscute
- Structura paginilor BVB se poate schimba → teste pe HTML salvat, alertă la eșecul scraper-ului.
- Protecția anti-bot BVB poate bloca și browserul headless → fallback: rulare cu browser vizibil sau Yahoo pentru prețuri.
- Rapoartele trimestriale în PDF au formate diferite → extragerea nu va fi 100% automată.
- Lichiditate redusă → metricile statistice pe acțiuni mici sunt nesigure; trebuie afișate cu avertisment.
