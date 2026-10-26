# Testing and verification

## Entry points

Run `python3 scripts/verify.py` from the repository root. It runs, in order:

1. `scripts/check_repository.py`: required files, text hygiene (LF, final newline, no trailing whitespace), local Markdown links, valid JSON, pinned workflow actions, no credential files, no data files (`*.duckdb`, `data/`) or oversized files committed.
2. The repository-guard tests in `scripts/tests/` (standard library `unittest`).
3. `uv sync --locked`, `uv run ruff format --check`, `uv run ruff check`, `uv run pytest`.

`python3 scripts/verify.py --repository-only` runs only steps 1–2, for documentation and tooling work; it does not verify the application. It stops on the first failed command and reports a missing `uv` as a failure, not a pass.

## Select checks by changed behavior

| Change | Evidence needed |
| --- | --- |
| Documentation | Repository checks; accurate claims about what is implemented. |
| Parser for a page or file | Fixture test with a minimal synthetic sample (`tests/fixtures/`): the real page's structure and quirks with invented issuers and values, plus a changed-shape failure case; then one real run and a spot check against the page. |
| Price adjustment, dividends, capital events | Hand-computed expected series for each event type (bonus, consolidation, dividend, both on one day); reconciliation on real data (`bvb reconcile`, comparison with the BVB adjusted series). |
| Analytics, valuation, risk | Small synthetic inputs with independently derived results (CAGR, drawdown, VaR quantiles, ROE averages); point-in-time checks. |
| Backtest | Single-stock no-cost run equals the total-return series; tax, fees, rebalancing, delisting cases. |
| DuckDB SQL / schema | Test against a temporary database created with `db.connect(tmp_path / ...)`; additive migration on an existing database. |
| Collector behavior | Fetching is not unit-tested against live sites. Test parsing and storage; run the collector once for real and report the counts. |
| Dashboard | Start it (`uv run bvb dashboard`), open every changed page in the browser, check there are no errors and the numbers match the CLI. |

Use the minimum useful suite for the change; protect invariants and regressions rather than a coverage number. Do not mock DuckDB to claim SQL correctness.

## Fixtures and isolation

- Tests never touch `data/` or the network. Use `tmp_path` databases and fixtures.
- Fixtures are minimal and synthetic: copy the structure of one issuer page or trading-day table (ids, nesting, number and date formats, empty and extra cells), then replace every issuer, name and value. The repository is public; a saved real page would redistribute BVB data.
- Use deterministic dates; avoid `today()` in assertions unless the test controls the relationship.

## Honest results

Record commands and outcomes. Separate passed, failed, not run and not applicable. A failing or skipped check is reported as such; never weaken a rule to get a pass. A narrow suppression (`# noqa: XXX`) needs a reason in the same line or the PR.
