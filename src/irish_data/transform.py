"""Turn a raw CSO JSON-stat response into a flat list of rows."""

import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from itertools import product
from math import prod
from pathlib import Path

RAW_DIR = Path("data/raw")  # same folder extract.py writes to


@dataclass
class Dimension:
    """One axis of the table, e.g. Month or Type of Residential Property."""
    id: str
    label: str
    role: str | None            # "time", "metric", or None
    codes: list[str]            # category codes, in position order
    labels: dict[str, str]      # code -> readable name
    units: dict[str, str]       # code -> unit (only some dimensions have these)


@dataclass
class ParsedTable:
    title: str
    source: str
    updated: str
    dimensions: list[Dimension]
    total_cells: int
    rows: list[dict]            # one dict per value that is not null


def period_to_date(code: str) -> date:
    """Convert a CSO period code to the first day of that period.

    "200501" -> 2005-01-01  (monthly)
    "2005Q2" -> 2005-04-01  (quarterly)
    "2005"   -> 2005-01-01  (yearly)
    """
    if re.fullmatch(r"\d{6}", code):
        return date(int(code[:4]), int(code[4:]), 1)
    quarter = re.fullmatch(r"(\d{4})Q([1-4])", code)
    if quarter:
        return date(int(quarter.group(1)), (int(quarter.group(2)) - 1) * 3 + 1, 1)
    if re.fullmatch(r"\d{4}", code):
        return date(int(code), 1, 1)
    raise ValueError(f"Unrecognised period code: {code!r}")


def _unwrap(raw: dict) -> dict:
    """The dataset sits under a single top-level key ("dataset" for the CSO)."""
    if len(raw) != 1:
        raise ValueError(f"Expected one top-level key, found {list(raw)}")
    dataset = next(iter(raw.values()))
    for key in ("dimension", "value"):
        if key not in dataset:
            raise ValueError(f"Missing '{key}' - is this a JSON-stat 1.0 table?")
    return dataset


def _read_dimension(dim_id: str, dim: dict, roles: dict) -> Dimension:
    category = dim["category"]
    index = category["index"]
    if isinstance(index, dict):
        codes = sorted(index, key=index.get)   # order by position number
    else:
        codes = list(index)                    # already an ordered list
    labels = category.get("label", {})
    units = {code: info.get("base", "") for code, info in category.get("unit", {}).items()}
    role = next((name for name, ids in roles.items() if dim_id in ids), None)
    return Dimension(
        id=dim_id,
        label=dim.get("label", dim_id),
        role=role,
        codes=codes,
        labels={code: labels.get(code, code) for code in codes},
        units=units,
    )


def parse_table(raw: dict) -> ParsedTable:
    """Flatten a JSON-stat 1.0 response into rows."""
    dataset = _unwrap(raw)
    dim_block = dataset["dimension"]
    sizes = dim_block["size"]
    roles = dim_block.get("role", {})
    dimensions = [_read_dimension(dim_id, dim_block[dim_id], roles) for dim_id in dim_block["id"]]

    for dim, size in zip(dimensions, sizes):
        if len(dim.codes) != size:
            raise ValueError(f"{dim.id}: expected {size} categories, found {len(dim.codes)}")

    values = dataset["value"]
    total = prod(sizes)
    if len(values) != total:
        raise ValueError(f"Expected {total} values from sizes {sizes}, got {len(values)}")

    time_dim = next((d for d in dimensions if d.role == "time"), None)
    period_dates = {}
    if time_dim:
        period_dates = {code: period_to_date(code).isoformat() for code in time_dim.codes}

    rows = []
    positions = product(*(range(size) for size in sizes))
    for position, value in zip(positions, values):
        if value is None:
            continue
        row = {dim.id: dim.codes[i] for dim, i in zip(dimensions, position)}
        if time_dim:
            row["period"] = period_dates[row[time_dim.id]]
        row["value"] = value
        rows.append(row)

    return ParsedTable(
        title=dataset.get("label", ""),
        source=dataset.get("source", ""),
        updated=dataset.get("updated", ""),
        dimensions=dimensions,
        total_cells=total,
        rows=rows,
    )


def find_raw_file(arg: str) -> Path:
    """Accept a .json path, or a table code (then use the newest saved file)."""
    path = Path(arg)
    if path.suffix == ".json":
        return path
    matches = sorted(RAW_DIR.glob(f"{arg.upper()}_*.json"))
    if not matches:
        sys.exit(f"No saved files for {arg} in {RAW_DIR}. Run extract.py first.")
    return matches[-1]


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("Usage: python src/irish_data/transform.py TABLE_CODE_OR_FILE")
    path = find_raw_file(sys.argv[1])
    table = parse_table(json.loads(path.read_text(encoding="utf-8")))

    print(f"File:     {path}")
    print(f"Title:    {table.title}")
    print(f"Source:   {table.source}   (updated {table.updated})")
    for dim in table.dimensions:
        print(f"  {dim.id:<14} {dim.label:<30} role={dim.role}  categories={len(dim.codes)}")
    print(f"Cells: {table.total_cells}   With data: {len(table.rows)}")
    print("First 5 rows:")
    for row in table.rows[:5]:
        print(f"  {row}")


if __name__ == "__main__":
    main()