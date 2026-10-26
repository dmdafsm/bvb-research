import json
from datetime import datetime

import duckdb

from bvb.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS instruments (
    symbol      VARCHAR PRIMARY KEY,
    name        VARCHAR,
    isin        VARCHAR,
    market      VARCHAR,          -- REGS = piata reglementata, XRS1 = AeRO, INDEX = indice
    yahoo       VARCHAR,          -- ticker Yahoo, NULL daca nu exista
    first_seen  DATE,
    last_seen   DATE
);

CREATE TABLE IF NOT EXISTS prices_eod (
    date        DATE    NOT NULL,
    symbol      VARCHAR NOT NULL,
    source      VARCHAR NOT NULL, -- 'bvb' (sumar zilnic) | 'bvb_hist' (grafic) | 'yahoo'
    market      VARCHAR,
    open        DOUBLE,
    high        DOUBLE,
    low         DOUBLE,
    close       DOUBLE,
    avg_price   DOUBLE,
    ref_price   DOUBLE,
    change_pct  DOUBLE,
    volume      BIGINT,
    value       DOUBLE,
    trades      INTEGER,
    adj_close   DOUBLE,           -- ajustat de sursa (bvb_hist, yahoo); pentru validare
    PRIMARY KEY (date, symbol, source)
);

CREATE TABLE IF NOT EXISTS corporate_events (
    date        DATE    NOT NULL,
    symbol      VARCHAR NOT NULL,
    source      VARCHAR NOT NULL,
    kind        VARCHAR NOT NULL, -- 'dividend' | 'split'
    amount      DOUBLE,           -- dividend pe actiune
    ratio       DOUBLE,           -- split: numerator / denominator
    PRIMARY KEY (date, symbol, source, kind)
);

ALTER TABLE instruments ADD COLUMN IF NOT EXISTS isin VARCHAR;
ALTER TABLE instruments ADD COLUMN IF NOT EXISTS segment VARCHAR;
ALTER TABLE instruments ADD COLUMN IF NOT EXISTS category VARCHAR;
ALTER TABLE instruments ADD COLUMN IF NOT EXISTS status VARCHAR;
ALTER TABLE instruments ADD COLUMN IF NOT EXISTS cui VARCHAR;
ALTER TABLE instruments ADD COLUMN IF NOT EXISTS activity VARCHAR;
ALTER TABLE instruments ADD COLUMN IF NOT EXISTS website VARCHAR;
ALTER TABLE instruments ADD COLUMN IF NOT EXISTS shares BIGINT;
ALTER TABLE instruments ADD COLUMN IF NOT EXISTS nominal_value DOUBLE;
ALTER TABLE instruments ADD COLUMN IF NOT EXISTS listing_date DATE;
ALTER TABLE instruments ADD COLUMN IF NOT EXISTS issuer_updated TIMESTAMP;

-- Din fisa emitentului (istoric complet, inlocuit la fiecare actualizare).
CREATE TABLE IF NOT EXISTS dividends (
    symbol        VARCHAR NOT NULL,
    fiscal_year   INTEGER,
    amount        DOUBLE,           -- RON brut pe actiune
    agm_date      DATE,
    record_date   DATE,
    ex_date       DATE,
    declared_date DATE,
    pay_date      DATE
);

CREATE TABLE IF NOT EXISTS capital_changes (
    symbol         VARCHAR NOT NULL,
    change_date    DATE,
    agm_date       DATE,
    ref_date       DATE,
    record_date    DATE,
    operation      VARCHAR,
    shares_before  BIGINT,
    shares_after   BIGINT,
    nominal_before DOUBLE,
    nominal_after  DOUBLE
);

CREATE SEQUENCE IF NOT EXISTS ingest_log_seq;
CREATE TABLE IF NOT EXISTS ingest_log (
    id          BIGINT DEFAULT nextval('ingest_log_seq') PRIMARY KEY,
    ts          TIMESTAMP NOT NULL,
    job         VARCHAR NOT NULL,
    params      VARCHAR,
    status      VARCHAR NOT NULL, -- 'ok' | 'error'
    rows        INTEGER,
    message     VARCHAR
);

-- Un singur pret pe zi si simbol: sumar BVB > grafic BVB > Yahoo.
CREATE OR REPLACE VIEW prices AS
SELECT * EXCLUDE (rn) FROM (
    SELECT *, row_number() OVER (
        PARTITION BY date, symbol
        ORDER BY CASE source WHEN 'bvb' THEN 0 WHEN 'bvb_hist' THEN 1 ELSE 2 END
    ) AS rn
    FROM prices_eod
) WHERE rn = 1;
"""


def connect(path=DB_PATH) -> duckdb.DuckDBPyConnection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute(SCHEMA)
    return con


def log_ingest(con, job: str, params: dict, status: str, rows: int = 0, message: str = "") -> None:
    con.execute(
        "INSERT INTO ingest_log (ts, job, params, status, rows, message) VALUES (?, ?, ?, ?, ?, ?)",
        [datetime.now(), job, json.dumps(params, default=str), status, rows, message],
    )
