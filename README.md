# Irish Open Data Pipeline

A Python pipeline that downloads official Irish statistics from the Central Statistics Office (CSO) API, cleans them, and stores them in a SQLite database so they can be queried and analysed with SQL.

It starts with one dataset, the **Residential Property Price Index (HPM09)**, but is written to handle any CSO time-series table.

> **Status: in progress.** The extract, transform and load stages work. SQL analysis, tests, CI and a command-line interface are planned (see [Roadmap](#roadmap)).

## Why this project

Public statistics are easy to find but awkward to use. The CSO returns each table in JSON-stat format: a single flat list of numbers, plus a separate legend describing what each position means. This project turns that into tidy, labelled rows in a relational database, and makes the whole process **repeatable**: running it again never duplicates data, and a failed run never leaves the database half-loaded.

## How it works

```
CSO PxStat API ──► extract ──► transform ──► load ──► SQLite ──► SQL queries
 (JSON-stat)       raw JSON     labelled      upsert    data/       (planned:
                   snapshot     rows          in one    pipeline.db  analysis)
                   on disk                    transaction
```

| Stage | File | What it does |
|---|---|---|
| **Extract** | `src/irish_data/extract.py` | Downloads a table by its CSO code. Uses a request timeout, retries with exponential backoff on server and network errors, and fails immediately with a clear message on an unknown table code. Saves the untouched response to `data/raw/` with a UTC timestamp. |
| **Transform** | `src/irish_data/transform.py` | Reads a saved response and unpacks the flat value array into labelled rows. Works out each value's category from its position, skips missing values, and converts CSO period codes (e.g. `200501`) into ISO dates (`2005-01-01`). |
| **Load** | `src/irish_data/load.py` | Writes the rows into SQLite inside a single transaction, using upserts so repeated runs don't create duplicates. Records every run in an `ingestion_runs` table. |

Saving the raw response first means the later stages can be re-run, debugged or changed without calling the API again.

## Data source

- **Publisher:** Central Statistics Office, Ireland ([data.cso.ie](https://data.cso.ie))
- **API:** PxStat `ReadDataset`, JSON-stat 1.0
- **First dataset:** [HPM09 – Residential Property Price Index](https://data.gov.ie/dataset/hpm09-residential-property-price-index), a monthly index (base 2015 = 100) by property type and region, plus the CSO's own 1-month, 3-month and 12-month percentage changes.

Each table is published under its own licence; HPM09 is listed as Creative Commons Attribution 4.0. Downloaded data is **not** stored in this repository.

## Getting started

**Requirements:** Python 3.11 or newer.

```bash
# 1. Clone and enter the project
git clone https://github.com/dylancoady1/irish-open-data-pipeline.git
cd irish-open-data-pipeline

# 2. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install the only dependency
pip install requests
```

Run each stage from the project's top-level folder:

```bash
python src/irish_data/extract.py HPM09     # download -> data/raw/HPM09_<timestamp>.json
python src/irish_data/transform.py HPM09   # parse the newest saved file and print a summary
python src/irish_data/load.py HPM09        # load it into data/pipeline.db
```

`load.py` prints how many rows it parsed, inserted and updated. **Run it a second time:** because loading is idempotent, an unchanged dataset reports `inserted 0, updated 0`.

To use a different CSO table, pass its code instead of `HPM09`. Find codes by searching [data.cso.ie](https://data.cso.ie). The table needs a time dimension (monthly, quarterly or yearly).

## Database design

Each CSO table is a collection of **time series** (one line on a chart, such as "price index, Dublin, all properties"). The schema reflects that:

```
datasets ──< series ──< observations
                │
                └──< series_attributes

ingestion_runs   (log of every load attempt)
```

| Table | One row per | Key columns |
|---|---|---|
| `datasets` | CSO table loaded | `code`, `title`, `source_updated`, `last_fetched` |
| `series` | time series | `dataset`, `key` (e.g. `HPM09C01\|04`), `label`, `unit` |
| `series_attributes` | dimension of a series | `series_id`, `dimension_id`, `code`, `label` |
| `observations` | value in a period | `series_id`, `period` (ISO date), `value` |
| `ingestion_runs` | load attempt | `rows_parsed`, `rows_inserted`, `rows_updated`, `status`, `message` |

The full definitions are in [`sql/schema.sql`](sql/schema.sql).

### Design decisions

- **Normalised schema.** Long labels like "Residential Property Price Index | National - houses" are stored once in `series`, not repeated on every observation.
- **Idempotent loads.** `observations` has a composite primary key `(series_id, period)` and rows are written with `INSERT ... ON CONFLICT DO UPDATE`, so a series can only ever have one value per period. Values are only updated when they have actually changed, which lets the loader report real inserts and updates separately.
- **All-or-nothing transactions.** A load either commits completely or rolls back. Failed runs are still recorded in `ingestion_runs`, with the error message.
- **Parameterised queries.** All SQL uses `?` placeholders, never string formatting.
- **Foreign keys switched on explicitly.** SQLite ignores them by default, so each connection enables them.
- **Dates as ISO text.** SQLite has no date type; `YYYY-MM-DD` text sorts correctly and works with SQLite's date functions.
- **Generic parser.** The time dimension is found through the response's `role` metadata, not hard-coded to HPM09.
- **Fail loudly.** The parser checks that the number of values matches the table's declared dimensions and raises a clear error otherwise, rather than producing wrong data.

## Example queries

Open the database with `sqlite3 data/pipeline.db`, then try:

```sql
-- Which series were loaded?
SELECT id, key, label, unit
FROM series
WHERE dataset = 'HPM09'
ORDER BY key;
```

```sql
-- Latest price index for each series
SELECT s.label, o.period, o.value
FROM observations o
JOIN series s ON s.id = o.series_id
WHERE s.dataset = 'HPM09'
  AND s.key LIKE 'HPM09C01|%'
  AND o.period = (SELECT MAX(period) FROM observations WHERE series_id = s.id)
ORDER BY o.value DESC;
```

```sql
-- Year-on-year change for the national index (window function)
SELECT period,
       value,
       ROUND(100.0 * (value / LAG(value, 12) OVER (ORDER BY period) - 1), 1) AS yoy_pct
FROM observations
WHERE series_id = (SELECT id FROM series WHERE dataset = 'HPM09' AND key = 'HPM09C01|-')
ORDER BY period;
```

```sql
-- Recent load history
SELECT run_at, dataset, rows_parsed, rows_inserted, rows_updated, status
FROM ingestion_runs
ORDER BY id DESC
LIMIT 5;
```

The year-on-year query assumes the series has no missing months, which holds for the national HPM09 series. The CSO also publishes its own 12-month change (`HPM09C04`), which makes a useful cross-check.

## Project structure

```
.
├── src/irish_data/
│   ├── extract.py       # download and save raw responses
│   ├── transform.py     # JSON-stat -> labelled rows
│   ├── load.py          # rows -> SQLite
│   └── config.py        # shared file paths
├── sql/
│   └── schema.sql       # table definitions
├── data/                # created at runtime, not committed
│   ├── raw/             # saved API responses
│   └── pipeline.db      # SQLite database
└── README.md
```

## Known limitations

- Only time-series tables with a time dimension can be loaded.
- Only the JSON-stat 1.0 response format is supported.
- Monthly period codes (`200501`) are the format HPM09 uses and are handled. Quarterly (`2005Q2`) and yearly (`2005`) codes are implemented from the expected format but have not yet been tried on a real table; anything unrecognised raises an error rather than being guessed.
- Scripts are meant to be run from the project's top-level folder.

## Roadmap

- [ ] SQL analysis in `sql/queries/`: year-on-year change, Dublin versus the rest of the country, peak-to-trough, rolling averages
- [ ] Validate calculated changes against the CSO's published 12-month figures
- [ ] Unit tests with `pytest` using a small saved sample response
- [ ] GitHub Actions workflow to run the tests on every push
- [ ] Command-line interface (`ingest`, `report`, `status`)
- [ ] Report output (CSV export and charts)
- [ ] Load further CSO tables

## Acknowledgements and licence

Data: Central Statistics Office, Ireland, from [data.cso.ie](https://data.cso.ie), used under the licence stated for each table (HPM09: CC BY 4.0). This project is not affiliated with or endorsed by the CSO.

Code: MIT licence. See [`LICENSE`](LICENSE).
