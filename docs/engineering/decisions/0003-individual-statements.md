# ADR 0003: fundamentals from data.gov.ro individual statements

Status: accepted. Date: 2026-10-26. Related tasks: P4.

## Context

Valuation and quality metrics need multi-year financial statements. Options checked:

- BVB issuer page, "Informatii financiare" tab: three years of key balance-sheet lines as text; the per-period indicator pages render values as encrypted images, a deliberate anti-extraction measure that we do not circumvent.
- ESEF filings on filings.xbrl.org: structured, but only ~115 Romanian filings and annual only.
- data.gov.ro "Situații financiare" datasets (Ministry of Finance, CC-BY 4.0): annual statements of all companies from 2008, one file per filer type (standard, IFRS, abbreviated, banks, SIF, insurers), matched to issuers by CUI.

## Decision

Use data.gov.ro as the fundamentals source (`bvb ingest fundamentals`). Stream the bulk files and keep only issuers' rows; map filer-specific labels to common fields (`revenue`, `net_profit`, `equity`, `total_assets`, `debts`, …) and keep every raw label in `fundamentals_raw`. For banks, take net profit from the consistent "Profit sau (-) pierdere aferent(a) exercitiului" line and do not use turnover.

## Alternatives and consequences

- These are **individual** (parent-only) statements, not consolidated: for holding companies and groups with large subsidiaries (for example Electrica, MedLife) multiples do not reflect the group and can be extreme. Reports and the dashboard label them as individual statements.
- Annual only; quarterly results (PDF reports on BVB) are not extracted.
- Fiscal year N is treated as available from 1 June N+1 for point-in-time valuation.
- Column order in some bank files does not match the descriptor; fields that depend on it are not used for banks.

## Verification

SNP 2024: total assets 56,329.7 million RON, equal to fixed + current assets + prepaid expenses on the BVB issuer page; SNP 2010 net profit 1.8 billion RON. Coverage after ingestion: ~205–240 issuers per year for 2009–2025.
