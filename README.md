# bvb-research

Instrument personal de analiză pentru companiile listate la BVB. Plan: [docs/plan.md](docs/plan.md), surse: [docs/surse-date.md](docs/surse-date.md).

## Instalare

```bash
uv sync
uv run playwright install chromium
uv run bvb init-db
```

## Prețuri EOD

```bash
uv run bvb ingest bvb            # sedintele noi de pe BVB (se opreste la prima zi existenta)
uv run bvb ingest bvb --full     # toata fereastra BVB (~30 zile), umple golurile
uv run bvb ingest history        # istoric complet din graficul BVB (brut + ajustat)
uv run bvb ingest yahoo          # optional: istoric Yahoo, pentru validare
uv run bvb reconcile             # inchideri sumar BVB vs grafic BVB (--other yahoo)
uv run bvb status
```

- Pagina de sumar BVB oferă doar ultimele ~30 de zile. Istoricul complet vine din API-ul graficului BVB (`source = 'bvb_hist'`, `adj_close` = ajustat de BVB), folosit cu acordul utilizatorului pentru uz personal.
- View-ul `prices` dă un singur preț pe zi și simbol: sumar BVB > grafic BVB > Yahoo.
- HTML-ul brut al fiecărei ședințe BVB se păstrează în `data/raw/bvb_summary/`.
- Datele sunt doar pentru uz personal (termenii BVB).

## Emitenți, indici, prețuri ajustate

```bash
uv run bvb ingest indices        # BET, BET-TR, BET-FI, BET-NG, ROTX etc.
uv run bvb ingest issuers        # fisa emitentului: ISIN, CUI, nr. actiuni, dividende, modificari capital
uv run bvb adjust                # recalculeaza prices_adj (adj_close, tr_close) + raport de verificare
```

- `prices_adj.adj_close`: ajustat pentru evenimente de capital (acțiuni gratuite, splituri, consolidări). Factorii vin din seria ajustată BVB; modificările de capital pe care BVB nu le-a ajustat se derivă din numărul de acțiuni, doar dacă saltul de preț le confirmă.
- `prices_adj.tr_close`: randament total cu dividende brute reinvestite (factor `P_ex / (P_ex + D)`).
- `adjust_events`: evenimentele aplicate (`capital`, `capital_derived`, `unknown`) și salturile BVB tratate ca dividend.
- Raportul „mișcări suspecte” = salturi > 40% care persistă 5 zile în randamentul total; majoritatea sunt acțiuni nelichide din anii '90–2000.

## Analiză și backtest

```bash
uv run bvb stock TLV                              # randament/risc pe 1/3/5/10 ani vs BET-TR, lichiditate, dividende
uv run bvb screen --years 3 --min-traded 0.8      # tabel comparativ actiuni REGS
uv run bvb backtest "TLV=0.4,SNP=0.3,H2O=0.3" --start 2020-01-01 --rebalance quarterly
uv run bvb backtest "TLV,SNP" --tax 0 --fee 0 --csv nav.csv
```

- Randamentele folosesc `tr_close` (dividende brute reinvestite); benchmark BET-TR, prelungit cu BET (fără dividende) înainte de 2014-09-19.
- Backtest: tranzacții la închidere, comision procentual, impozit pe dividende pe cotele istorice (`--tax auto`: 16% până în 2015, 5% 2016–2022, 8% 2023–2024, 10% 2025, 16% din 2026), dividende reinvestite în aceeași acțiune (`drip`) sau păstrate cash.
- În zilele fără tranzacții prețul e reportat: pentru acțiuni nelichide volatilitatea e subestimată și execuția e optimistă — verifică mereu coloana de lichiditate.

## Risc de portofoliu

```bash
uv run bvb ingest metadata                        # sector, industrie, moneda (o data)
uv run bvb risk "TLV=0.3,SNP=0.25,H2O=0.25,ARS=0.1,CRC=0.1" --value 200000 --horizon 1
```

- VaR/CVaR istoric (ferestre suprapuse pe orizont) și parametric (normal, covarianță Ledoit-Wolf), contribuția fiecărei poziții la risc.
- Corelații și beta pe randamente săptămânale (atenuează efectul prețurilor reportate la acțiunile nelichide).
- Stres: episoade istorice (2008, 2011, OUG 114/2018, COVID, Ucraina) și șocuri BET-TR prin beta; acțiunile nelistate atunci sunt aproximate prin beta (coloana `proxied`).
- Concentrare: HHI, sectoare, companii controlate de stat (din structura acționariatului), expunere non-RON.
- Lichiditate: zile necesare vânzării fiecărei poziții la max. 20% din valoarea medie zilnică (`--participation`).
- VaR-ul istoric reflectă doar fereastra aleasă (`--years`); o fereastră fără crize subestimează riscul — compară cu scenariile de stres.

## Date fundamentale și evaluare

```bash
uv run bvb ingest fundamentals                    # situatii financiare anuale 2008+ (data.gov.ro, CC-BY 4.0)
uv run bvb fundamentals SNP                       # istoric financiar, ROE, marja, payout, multipli actuali
uv run bvb valuation --sort pe --min-traded 0.8   # multipli pentru toata piata
```

- Situațiile de pe data.gov.ro sunt **individuale** (nu consolidate): pentru holdinguri (ex. Electrica, MedLife) multiplii nu reflectă grupul.
- Exercițiul N e considerat disponibil din 1 iunie N+1; capitalizarea istorică folosește numărul de acțiuni ajustat pentru evenimentele de capital.
- Valorile indicatorilor de pe paginile BVB „Indicatori financiari” sunt afișate ca imagini (protecție anti-extragere) și nu sunt folosite.

## Anunțuri, calendar, știri

```bash
uv run bvb watch add TLV SNP H2O                  # lista de urmarire
uv run bvb ingest reports --windows 3             # rapoarte curente, toti emitentii (~10 zile / fereastra)
uv run bvb ingest news                            # RSS ZF + Profit.ro, etichetate cu emitentii
uv run bvb ingest report-texts                    # text din PDF-urile rapoartelor (lista de urmarire)
uv run bvb reports -w --category insider          # categorii: insider, results, agm, dividend, buyback, nav, ...
uv run bvb reports --search "dividend special"
uv run bvb calendar -w --days 30                  # rezultate, AGA, date ex-dividend
uv run bvb news -w
```

## Dashboard, alerte, rulare zilnică

```bash
uv run bvb dashboard                              # http://localhost:8501 (Emitent, Screener, Portofoliu, Calendar)
uv run bvb alerts --notify                        # anunturi noi, ex-dividend in 7 zile, miscari > 5%
uv run bvb daily                                  # dupa 18:30: preturi, rapoarte, stiri, ajustari, alerte
uv run bvb daily --full                           # saptamanal: + istoric grafic, indici, fise emitenti
```

DuckDB permite un singur proces care scrie: oprește dashboard-ul în timpul colectărilor.

## Teste

```bash
uv run pytest
```
