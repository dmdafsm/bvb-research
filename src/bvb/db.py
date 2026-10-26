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
ALTER TABLE instruments ADD COLUMN IF NOT EXISTS sector VARCHAR;     -- din API-ul graficului BVB
ALTER TABLE instruments ADD COLUMN IF NOT EXISTS industry VARCHAR;
ALTER TABLE instruments ADD COLUMN IF NOT EXISTS currency VARCHAR;

CREATE TABLE IF NOT EXISTS shareholders (
    symbol  VARCHAR NOT NULL,
    as_of   DATE,
    holder  VARCHAR,
    shares  BIGINT,
    pct     DOUBLE                    -- procent din capital
);

-- Detinerea statului (central sau local) din structura actionariatului.
CREATE OR REPLACE VIEW state_ownership AS
SELECT symbol, sum(pct) AS state_pct
FROM shareholders
WHERE regexp_matches(upper(holder),
      'STATUL ROMAN|MINISTERUL|SECRETARIATUL GENERAL AL GUVERNULUI|MUNICIPIUL|CONSILIUL (JUDETEAN|LOCAL)|JUDETUL ')
GROUP BY symbol;

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

-- Situatii financiare anuale individuale (data.gov.ro).
CREATE TABLE IF NOT EXISTS fundamentals (
    symbol        VARCHAR NOT NULL,
    year          INTEGER NOT NULL,
    kind          VARCHAR NOT NULL,   -- IR | BL | UU | BANK | SIF | ASIG | VS
    cui           VARCHAR,
    caen          VARCHAR,
    revenue       DOUBLE,             -- cifra de afaceri neta
    total_revenue DOUBLE,
    net_profit    DOUBLE,
    equity        DOUBLE,
    total_assets  DOUBLE,
    debts         DOUBLE,
    cash          DOUBLE,
    employees     DOUBLE,
    PRIMARY KEY (symbol, year, kind)
);

CREATE TABLE IF NOT EXISTS fundamentals_raw (
    symbol VARCHAR, year INTEGER, kind VARCHAR, label VARCHAR, value DOUBLE
);

-- Un rand pe an si emitent (daca apare in mai multe fisiere, IFRS / banci / SIF au prioritate).
CREATE OR REPLACE VIEW fundamentals_annual AS
SELECT * EXCLUDE (rn) FROM (
    SELECT *, row_number() OVER (PARTITION BY symbol, year ORDER BY
        CASE kind WHEN 'IR' THEN 0 WHEN 'BANK' THEN 1 WHEN 'SIF' THEN 2 WHEN 'ASIG' THEN 3
                  WHEN 'VS' THEN 4 WHEN 'BL' THEN 5 ELSE 6 END) AS rn
    FROM fundamentals
) WHERE rn = 1;

-- Rapoarte curente / anunturi ale emitentilor (bvb.ro).
CREATE TABLE IF NOT EXISTS reports (
    symbol    VARCHAR NOT NULL,
    published TIMESTAMP NOT NULL,
    title     VARCHAR NOT NULL,
    category  VARCHAR,           -- dedusa din titlu: insider, dividend, results, agm, ...
    bvb_type  VARCHAR,           -- tipul afisat de BVB (pagina globala)
    url_ro    VARCHAR,
    url_en    VARCHAR,
    text      VARCHAR,           -- textul extras din PDF (doar pentru lista de urmarire)
    PRIMARY KEY (symbol, published, title)
);

CREATE TABLE IF NOT EXISTS calendar (
    symbol VARCHAR NOT NULL,
    date   DATE NOT NULL,
    kind   VARCHAR,              -- financial | agm
    event  VARCHAR
);

CREATE TABLE IF NOT EXISTS news (
    url       VARCHAR PRIMARY KEY,
    source    VARCHAR,
    published TIMESTAMP,
    title     VARCHAR,
    summary   VARCHAR,
    symbols   VARCHAR[]          -- emitentii mentionati
);

CREATE TABLE IF NOT EXISTS watchlist (
    symbol VARCHAR PRIMARY KEY,
    added  TIMESTAMP DEFAULT now()
);

-- Calculate de `bvb adjust`.
CREATE TABLE IF NOT EXISTS prices_adj (
    date DATE, symbol VARCHAR, close DOUBLE, cap_factor DOUBLE, div_factor DOUBLE,
    adj_close DOUBLE, tr_close DOUBLE, PRIMARY KEY (date, symbol)
);
CREATE TABLE IF NOT EXISTS adjust_events (symbol VARCHAR, date DATE, kind VARCHAR, ratio DOUBLE);

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


def connect(path=DB_PATH, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    if read_only:
        return duckdb.connect(str(path), read_only=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute(SCHEMA)
    return con


def log_ingest(con, job: str, params: dict, status: str, rows: int = 0, message: str = "") -> None:
    con.execute(
        "INSERT INTO ingest_log (ts, job, params, status, rows, message) VALUES (?, ?, ?, ?, ?, ?)",
        [datetime.now(), job, json.dumps(params, default=str), status, rows, message],
    )
