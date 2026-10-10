"""Shared settings: where things live on disk (paths are relative to the repo root)."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

RAW_DIR = PROJECT_ROOT / "data" / "raw"
DB_PATH = PROJECT_ROOT / "data" / "pipeline.db"
SCHEMA_FILE = PROJECT_ROOT / "sql" / "schema.sql"