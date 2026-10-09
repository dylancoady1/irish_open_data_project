import json 
import sys
import time
from  datetime import datetime, timezone
from pathlib import Path

import requests

BASE_URL =  "https://ws.cso.ie/public/api.restful/PxStat.Data.Cube_API.ReadDataset/{code}/JSON-stat/1.0/en"
RAW_DIR = Path("data/raw")

def create_url(table_code):
    # return API address
    return BASE_URL.format(code=table_code.upper())

def fetch_table(table_code: str, retries: int = 3, timeout: int = 30) -> dict:
    # return data as python dictionary
    url = create_url(table_code)

    for attempt in range(1, retries+1):
        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as error:
            if error.response.status_code < 500:
                raise
            print(f"Attempt {attempt}/{retries} failed: {error}")
        except (requests.RequestException, ValueError) as error:
            print(f"Attempt {attempt}/{retries} failed: {error}")
        if attempt == retries:
            raise RuntimeError(f"Could not fetch {table_code} after {retries} attempts")
        time.sleep(2 ** attempt)

def save_raw(data: dict, table_code: str, directory: Path = RAW_DIR) -> Path:
    """Write the response to a timestamped file and return its path."""
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"{table_code.upper()}_{stamp}.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("Usage: python src/irish_data/extract.py TABLE_CODE")
    table_code = sys.argv[1]
    data = fetch_table(table_code)
    path = save_raw(data, table_code)
    print(f"Saved {path}")


if __name__ == "__main__":
    main()