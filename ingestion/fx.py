"""Extracts daily ECB reference rates (GBP and USD per EUR) into landing/ecb/rates/.

Each run writes one file named after --until. Daily runs re-pull the last 10 days,
so the same rate appears in several files; deduplicate downstream.
"""
import argparse
import csv
import io
import json
import urllib.request
from datetime import date, timedelta
from pathlib import Path

URL = ("https://data-api.ecb.europa.eu/service/data/EXR/D.GBP+USD.EUR.SP00.A"
       "?startPeriod={start}&endPeriod={end}&format=csvdata")
BACKFILL_START = date(2023, 12, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--until", type=date.fromisoformat, default=date.today() - timedelta(days=1))
    ap.add_argument("--backfill", action="store_true", help=f"pull from {BACKFILL_START} instead of the last 10 days")
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent.parent / "landing")
    a = ap.parse_args()

    start = BACKFILL_START if a.backfill else a.until - timedelta(days=10)
    req = urllib.request.Request(URL.format(start=start, end=a.until), headers={"Accept": "text/csv", "User-Agent": "saas-revenue-analytics"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        rows = list(csv.DictReader(io.StringIO(resp.read().decode("utf-8"))))

    f = a.out / "ecb" / "rates" / f"{a.until.isoformat()}.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows))
    print(f"{len(rows)} rates ({start} to {a.until}) written to {f}")


if __name__ == "__main__":
    main()
