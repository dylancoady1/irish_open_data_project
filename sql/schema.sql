-- One row per CSO table we have loaded
CREATE TABLE IF NOT EXISTS datasets (
    code            TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    source          TEXT,
    source_updated  TEXT,                 -- when the CSO last updated the table
    last_fetched    TEXT NOT NULL         -- when we last loaded it
);

-- One row per time series (one line on a chart)
CREATE TABLE IF NOT EXISTS series (
    id       INTEGER PRIMARY KEY,
    dataset  TEXT NOT NULL REFERENCES datasets (code),
    key      TEXT NOT NULL,               -- e.g. 'HPM09C01|01'
    label    TEXT NOT NULL,
    unit     TEXT,
    UNIQUE (dataset, key)
);

-- What each series is made of, one row per dimension
CREATE TABLE IF NOT EXISTS series_attributes (
    series_id        INTEGER NOT NULL REFERENCES series (id),
    dimension_id     TEXT NOT NULL,
    dimension_label  TEXT NOT NULL,
    code             TEXT NOT NULL,
    label            TEXT NOT NULL,
    PRIMARY KEY (series_id, dimension_id)
);

-- The actual numbers
CREATE TABLE IF NOT EXISTS observations (
    series_id  INTEGER NOT NULL REFERENCES series (id),
    period     TEXT NOT NULL,             -- first day of the period, 'YYYY-MM-DD'
    value      REAL NOT NULL,
    PRIMARY KEY (series_id, period)
);

-- A log of every load attempt
CREATE TABLE IF NOT EXISTS ingestion_runs (
    id             INTEGER PRIMARY KEY,
    dataset        TEXT NOT NULL,
    run_at         TEXT NOT NULL,
    source_file    TEXT,
    rows_parsed    INTEGER,
    rows_inserted  INTEGER,
    rows_updated   INTEGER,
    status         TEXT NOT NULL CHECK (status IN ('ok', 'failed')),
    message        TEXT
);

CREATE INDEX IF NOT EXISTS idx_observations_period ON observations (period);
CREATE INDEX IF NOT EXISTS idx_attributes_lookup ON series_attributes (dimension_id, code);