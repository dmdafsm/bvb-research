# ADR 0002: read snapshot for the dashboard

Status: accepted. Date: 2026-10-26. Related tasks: P8.

## Context

DuckDB allows one process to open a database file for writing, and while it is open no other process can open it, not even read-only. Collectors can run for hours (delisted probing, issuer pages), which made the dashboard unusable during ingestion.

## Decision

Commands that write publish `data/bvb_read.duckdb` when the process exits: `CHECKPOINT` on the writer connection, copy to a temporary file, atomic `os.replace`. `bvb snapshot` publishes on demand. The dashboard opens only the snapshot, read-only, keyed on its modification time; when a newer snapshot appears it closes the old connection explicitly (DuckDB reuses an open instance for the same path) and reopens.

## Alternatives and consequences

- Short-lived connections with retries on both sides: no copy, but long or frequent writes still block readers intermittently.
- SQLite in WAL mode or PostgreSQL: concurrent readers and a writer, but slower analytics on time series and a broad rewrite of queries.
- Consequences: the dashboard shows data as of the last finished command (the sidebar shows the time); the snapshot doubles disk use (~100 MB). Long-running collectors publish only at exit.

## Verification

`tests/test_db.py`: the snapshot contains writes not yet checkpointed; an open reader keeps the old copy; a reconnect after closing sees the new one; no temporary file is left behind.
