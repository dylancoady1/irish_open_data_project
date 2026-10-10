"""Load a parsed CSO table into SQLite."""

import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from config import DB_PATH, SCHEMA_FILE
from transform import Dimension, ParsedTable, find_raw_file, parse_table


@dataclass
class LoadResult:
    parsed: int     # rows we tried to load
    inserted: int   # brand-new rows
    updated: int    # existing rows whose value changed


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Open the database (creating it if needed) and make sure the tables exist."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")   # SQLite ignores foreign keys unless asked
    conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
    return conn


def _count_observations(conn: sqlite3.Connection, dataset_code: str) -> int:
    return conn.execute(
        """
        SELECT COUNT(*)
        FROM observations o JOIN series s ON s.id = o.series_id
        WHERE s.dataset = ?
        """,
        (dataset_code,),
    ).fetchone()[0]


def _upsert_series(
    conn: sqlite3.Connection,
    dataset_code: str,
    series_dims: list[Dimension],
    codes: tuple,
) -> int:
    """Insert (or update) one series and its attributes. Return its id."""
    key = "|".join(codes)
    label = " | ".join(dim.labels[code] for dim, code in zip(series_dims, codes))
    unit = next(
        (dim.units[code] for dim, code in zip(series_dims, codes) if code in dim.units),
        None,
    )

    conn.execute(
        """
        INSERT INTO series (dataset, key, label, unit) VALUES (?, ?, ?, ?)
        ON CONFLICT (dataset, key) DO UPDATE SET label = excluded.label, unit = excluded.unit
        """,
        (dataset_code, key, label, unit),
    )
    series_id = conn.execute(
        "SELECT id FROM series WHERE dataset = ? AND key = ?", (dataset_code, key)
    ).fetchone()[0]

    for dim, code in zip(series_dims, codes):
        conn.execute(
            """
            INSERT INTO series_attributes (series_id, dimension_id, dimension_label, code, label)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (series_id, dimension_id) DO UPDATE SET
                dimension_label = excluded.dimension_label,
                code = excluded.code,
                label = excluded.label
            """,
            (series_id, dim.id, dim.label, code, dim.labels[code]),
        )
    return series_id


def _load_in_transaction(
    conn: sqlite3.Connection, dataset_code: str, table: ParsedTable
) -> LoadResult:
    time_dim = next((d for d in table.dimensions if d.role == "time"), None)
    if time_dim is None:
        raise ValueError("Table has no time dimension, so it can't be loaded as a time series")
    series_dims = [d for d in table.dimensions if d.role != "time"]

    conn.execute(
        """
        INSERT INTO datasets (code, title, source, source_updated, last_fetched)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (code) DO UPDATE SET
            title = excluded.title,
            source = excluded.source,
            source_updated = excluded.source_updated,
            last_fetched = excluded.last_fetched
        """,
        (dataset_code, table.title, table.source, table.updated, now_utc()),
    )

    series_ids: dict[tuple, int] = {}
    observations = []
    for row in table.rows:
        codes = tuple(row[d.id] for d in series_dims)
        if codes not in series_ids:
            series_ids[codes] = _upsert_series(conn, dataset_code, series_dims, codes)
        observations.append((series_ids[codes], row["period"], row["value"]))

    count_before = _count_observations(conn, dataset_code)
    changes_before = conn.total_changes
    conn.executemany(
        """
        INSERT INTO observations (series_id, period, value) VALUES (?, ?, ?)
        ON CONFLICT (series_id, period) DO UPDATE SET value = excluded.value
        WHERE observations.value IS NOT excluded.value
        """,
        observations,
    )
    changes = conn.total_changes - changes_before
    inserted = _count_observations(conn, dataset_code) - count_before
    return LoadResult(parsed=len(observations), inserted=inserted, updated=changes - inserted)


def _log_run(conn, dataset_code, source_file, parsed, inserted, updated, status, message):
    conn.execute(
        """
        INSERT INTO ingestion_runs
            (dataset, run_at, source_file, rows_parsed, rows_inserted, rows_updated, status, message)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (dataset_code, now_utc(), source_file, parsed, inserted, updated, status, message),
    )


def load_table(
    conn: sqlite3.Connection, dataset_code: str, table: ParsedTable, source_file: str = ""
) -> LoadResult:
    """Load a table in one all-or-nothing transaction and log the run."""
    dataset_code = dataset_code.upper()
    try:
        with conn:   # commits if the block succeeds, rolls back if it raises
            result = _load_in_transaction(conn, dataset_code, table)
            _log_run(conn, dataset_code, source_file,
                     result.parsed, result.inserted, result.updated, "ok", None)
        return result
    except Exception as error:
        with conn:
            _log_run(conn, dataset_code, source_file, None, None, None, "failed", str(error))
        raise


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("Usage: python src/irish_data/load.py TABLE_CODE_OR_FILE")
    path = find_raw_file(sys.argv[1])
    dataset_code = path.name.split("_")[0].upper()   # extract.py names files CODE_timestamp.json
    table = parse_table(json.loads(path.read_text(encoding="utf-8")))

    conn = connect()
    try:
        result = load_table(conn, dataset_code, table, source_file=str(path))
    finally:
        conn.close()
    print(
        f"{dataset_code}: parsed {result.parsed} rows, "
        f"inserted {result.inserted}, updated {result.updated}"
    )


if __name__ == "__main__":
    main()