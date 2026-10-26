"""Alerte pentru lista de urmarire: anunturi noi, date ex-dividend apropiate,
miscari mari de pret. Optional, notificare macOS (osascript)."""

import subprocess
from datetime import datetime

STATE_SQL = "CREATE TABLE IF NOT EXISTS alert_state (name VARCHAR PRIMARY KEY, ts TIMESTAMP)"


def collect(con, move_threshold: float = 0.05, exdiv_days: int = 7) -> list[str]:
    con.execute(STATE_SQL)
    last = con.execute("SELECT ts FROM alert_state WHERE name = 'reports'").fetchone()
    since = last[0] if last else datetime(1970, 1, 1)
    out = []

    for sym, published, cat, title in con.execute("""
            SELECT symbol, published, category, title FROM reports
            WHERE symbol IN (SELECT symbol FROM watchlist) AND published > ?
            ORDER BY published""", [since]).fetchall():
        out.append(f"[anunt] {sym} {published:%d.%m %H:%M} ({cat}): {title}")

    for sym, ex, amount in con.execute("""
            SELECT symbol, ex_date, amount FROM dividends
            WHERE symbol IN (SELECT symbol FROM watchlist)
              AND ex_date BETWEEN current_date AND current_date + to_days(?)
            ORDER BY ex_date""", [exdiv_days]).fetchall():
        out.append(f"[ex-dividend] {sym} pe {ex:%d.%m}: {amount} RON/actiune (cumpara cel tarziu in ziua anterioara)")

    for sym, day, ret in con.execute("""
            WITH r AS (
                SELECT symbol, date, tr_close / lag(tr_close) OVER (PARTITION BY symbol ORDER BY date) - 1 AS ret,
                       row_number() OVER (PARTITION BY symbol ORDER BY date DESC) AS rn
                FROM prices_adj WHERE symbol IN (SELECT symbol FROM watchlist))
            SELECT symbol, date, ret FROM r WHERE rn = 1 AND abs(ret) >= ?
            ORDER BY abs(ret) DESC""", [move_threshold]).fetchall():
        out.append(f"[pret] {sym} {ret:+.1%} pe {day:%d.%m}")

    con.execute("INSERT OR REPLACE INTO alert_state VALUES ('reports', now())")
    return out


def notify(lines: list[str], title: str = "BVB") -> None:
    if not lines:
        return
    body = "; ".join(lines[:3]) + (f" (+{len(lines) - 3})" if len(lines) > 3 else "")
    script = f"display notification {_quote(body)} with title {_quote(title)}"
    subprocess.run(["osascript", "-e", script], check=False, capture_output=True)


def _quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
