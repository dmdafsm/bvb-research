# ADR 0001: price history from the BVB chart API

Status: accepted. Date: 2026-10-26. Related tasks: P1, P2.

## Context

The public BVB daily trading summary page only allows selecting the last ~30 sessions. Long price history is needed for analytics and backtests. Yahoo Finance has partial `.RO` coverage and returned HTTP 429 to automated requests; Stooq requires a JavaScript bot check. The chart on each BVB issuer page loads its data from `https://wapi.bvb.ro/api/history` (TradingView UDF format), with raw (`ajust=0`) and BVB-adjusted (`ajust=1`) daily bars back to the 1990s, and `/api/symbols` with sector, industry and currency.

An automated permission check initially blocked calling this internal endpoint directly. The maintainer then explicitly approved using it for personal use (2026-10-26).

## Decision

Use the chart API for full daily history (`bvb ingest history`), index history (`bvb ingest indices`), instrument metadata (`bvb ingest metadata`) and delisted shares (`bvb ingest delisted`). Use the daily summary page for the latest sessions and as the preferred source on overlapping days. Keep usage personal and polite: sequential requests with delays, weekly refresh of full history, no redistribution.

## Alternatives and consequences

- Yahoo / Stooq: incomplete or blocked; kept only as an optional validation source.
- Buying BVB data: possible later if the tool is ever shared; not needed for personal use.
- The endpoint is undocumented and may change or be restricted. The collectors fail loudly; the daily summary page remains a fallback for recent data.
- The BVB adjusted series adjusts capital events but not cash dividends consistently, and misses some older events; `adjust.py` compensates ([architecture](../../architecture.md)).

## Verification

Reconciled closes between the summary page and the chart API on 20 overlapping sessions for all 264 symbols: no differences. TLV history from 1997-10-15, BET from 1997-09-22.
