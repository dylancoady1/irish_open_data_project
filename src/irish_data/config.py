"""Shared settings: where things live on disk (paths are relative to the repo root)."""

from pathlib import Path

RAW_DIR = Path("data/raw")
DB_PATH = Path("data/pipeline.db")
SCHEMA_FILE = Path("sql/schema.sql")