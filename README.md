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

## Teste

```bash
uv run pytest
```
