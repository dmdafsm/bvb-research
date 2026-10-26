# ADR 0004: Docker Compose for ingestion and the dashboard

Status: accepted. Date: 2026-10-26. Related tasks: P8, REPO.

## Context

The maintainer wants the dashboard and the daily collection to keep running without open terminals or a launchd job, still on their own Mac. AGENTS.md rules out background daemons and new infrastructure by default and binds the dashboard to localhost; this records the departure.

## Decision

`compose.yaml` runs two services built from one multi-stage `Dockerfile`:

- `ingest` (Playwright Python image, Chromium included) runs `bvb schedule`: `bvb daily` Monday to Friday at 19:15 and `bvb daily --full` on Saturday at 10:00, Europe/Bucharest. Jobs run one after another, each in its own process, so there is a single writer and each run publishes the read snapshot (ADR 0002). It mounts `./data` read-write.
- `dashboard` (python:3.12-slim) runs Streamlit on `0.0.0.0` inside the container, mounts `./data` read-only and is published only on `127.0.0.1:8501` of the host. `bvb dashboard` keeps `127.0.0.1` as its default.

Data stays in `./data` on the host (bind mount), so the containers and `uv run bvb ...` on the host see the same files; nothing is copied into images. Remote access (a tunnel with an identity check) is a separate decision.

## Alternatives and consequences

- launchd on the host: no Docker, but persistent system configuration and terminals for the dashboard.
- A named volume instead of the bind mount: faster DuckDB writes on macOS, but the data is no longer visible to host commands.
- Consequences: only one writer may run, so host `uv run bvb ingest ...`, `adjust` or `watch` must not run while the `ingest` container is running a job (DuckDB locks are not reliable across the macOS/VM bind mount); read-only host commands are fine against the snapshot. macOS notifications (`--notify`, `osascript`) are unavailable in the container; alerts go to the container log. Runs missed while the Mac sleeps start at wake-up (the scheduler checks the clock every minute). The ingest image is about 1.5 GB because of Chromium. The Playwright image tag must match `playwright` in `uv.lock`.

## Verification

`docker compose build` succeeded. In the ingest image: Python 3.12, `TZ` Europe/Bucharest, non-root `pwuser`, headless Chromium rendered a test page, and `bvb watch add` wrote a test database and published `bvb_read.duckdb` in a scratch data directory. The dashboard image served `/_stcore/health` and the app on a read-only mount of that snapshot. `tests/test_scheduler.py` covers the schedule. A full `bvb daily` against BVB in the container is still to be run after the host's delisted ingestion finishes (one process per site).
