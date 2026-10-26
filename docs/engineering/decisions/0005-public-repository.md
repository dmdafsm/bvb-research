# ADR 0005: public repository, private data

Status: accepted. Date: 2026-10-26. Related tasks: REPO.

## Context

The repository started private because everything derived from BVB data falls under BVB's personal-use terms, and the first parser tests used saved BVB pages (a full trading-day summary and one issuer page) and copied report rows. The maintainer decided to make the repository public.

## Decision

The repository is public and contains code and documentation only. Collected data, raw downloads, the DuckDB files and anything copied from a source page stay on the maintainer's machine (`data/`, `.research/`, ignored by git). Test fixtures and test strings are synthetic: the source page's structure and quirks with invented issuers and values. The code is licensed under MIT; the README states that the project is unofficial, ships no market data, uses an undocumented BVB endpoint and that users are responsible for complying with the sources' terms.

## Alternatives and consequences

- Keep the repository private: no exposure, but no sharing of the code.
- Publish with the real fixtures: simpler tests, but it would redistribute BVB data.
- Consequences: new parser tests need a synthetic fixture; real pages are used only locally for the real-data check. The real fixtures remain in the git history of commits made before this change; removing them from history requires rewriting it (force push) or starting a fresh public repository, which is the maintainer's decision.

## Verification

`tests/fixtures/` holds `bvb_summary_synthetic.html` and `issuer_synthetic.html`; the summary, issuer, calendar and issuer-news parsers pass against them (`python3 scripts/verify.py`). `git grep` finds no real BVB rows in tests.
