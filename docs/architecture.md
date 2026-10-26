# Architecture

A single Python package (`src/bvb`) with a Typer CLI, one DuckDB file and a Streamlit dashboard. Everything runs locally on the maintainer's machine.

## Data flow

```
sources ──(bvb ingest …)──> data/raw/ (HTML, JSON)      ┐
                       └──> data/bvb.duckdb  (writer)    │  one writing process at a time
                                │ CHECKPOINT + copy at exit
                                ▼
                       data/bvb_read.duckdb (snapshot) ──> bvb dashboard (read-only)
                                ▲
analytics / CLI reports read data/bvb.duckdb directly
```

- **Collectors** (`bvb/ingest/`) download, save raw pages where useful and write their own tables.
- **Derivations** (`adjust`) recompute tables from collected data and can always be rebuilt.
- **Analytics** (`analytics`, `valuation`, `portfolio`, `risk`) are pure reads plus pandas/numpy; they never call the network.
- **Presentation**: `cli.py` (text reports), `dashboard.py` (Streamlit), `alerts.py`.
- **Scheduling**: `scheduler.py` (`bvb schedule`), used by the `ingest` container in `compose.yaml` ([ADR 0004](engineering/decisions/0004-docker-compose.md)).

## Modules and table ownership

| Module | Source | Writes |
| --- | --- | --- |
| `ingest/bvb_summary.py` | BVB daily trading summary page (last ~30 sessions), Playwright | `prices_eod` (`source='bvb'`), `instruments` (symbol, market, first/last seen) |
| `ingest/bvb_history.py` | BVB chart API (`wapi.bvb.ro`), see [ADR 0001](engineering/decisions/0001-bvb-chart-api.md) | `prices_eod` (`source='bvb_hist'`, raw + BVB-adjusted), `instruments` (sector, industry, currency) |
| `ingest/issuer.py` | BVB issuer page tabs (Sumar, Emitent, Stiri), Playwright | `instruments` (ISIN, CUI, shares, …), `dividends`, `capital_changes`, `shareholders` |
| `ingest/reports.py` | BVB current reports page + issuer Stiri tab | `reports`, `calendar` |
| `ingest/news.py` | RSS (ZF, Profit.ro) | `news` |
| `ingest/datagov.py` | data.gov.ro annual financial statements (CC-BY 4.0), see [ADR 0003](engineering/decisions/0003-individual-statements.md) | `fundamentals`, `fundamentals_raw` |
| `ingest/delisted.py` + `cli.ingest_delisted` | BVB advanced search (incl. delisted) + chart API | `instruments` (`market='DELISTED'`), `delisted_probe`, `prices_eod` |
| `ingest/yahoo.py` | Yahoo Finance (validation only, often rate limited) | `prices_eod` (`source='yahoo'`), `corporate_events` |
| `adjust.py` | derived | `prices_adj`, `adjust_events` |
| `alerts.py` | derived | `alert_state` |
| `cli.py` (watch) | user | `watchlist` |
| `db.py` | — | schema, `ingest_log`, read snapshot |

Views: `prices` (one price per day and symbol: summary > chart > Yahoo), `fundamentals_annual` (one filing per year), `state_ownership`.

## Key conventions

- **Calendar**: BVB trading days are the dates of the BET index. Series are forward-filled on that calendar only after a symbol's first trade.
- **Adjusted prices**: `adj_close` removes capital events (bonus shares, splits, consolidations); `tr_close` also reinvests gross dividends. Capital factors come from the BVB adjusted series, with capital changes BVB missed derived from share counts when the price move confirms them. See `adjust.py`.
- **Point in time**: annual statements count as available from 1 June of the next year; historical market cap uses current shares × cap factor.
- **Units**: prices in RON per share; fundamentals in RON (not thousands); percentages stored as fractions.

## Schema evolution

The schema lives in `db.SCHEMA` and is applied on every write connection. Changes are additive (`CREATE … IF NOT EXISTS`, `ALTER TABLE … ADD COLUMN IF NOT EXISTS`, `CREATE OR REPLACE VIEW`). A breaking change documents how to rebuild the affected tables from `data/raw/` or by re-running the collectors.
