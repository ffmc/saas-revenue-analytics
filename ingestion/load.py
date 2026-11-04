"""Loads landing/ files into the RAW database.

JSONL folders landing/<source>/<object>/ map to RAW.<SOURCE>.<OBJECT>. Files are PUT
to the RAW.PUBLIC.LANDING stage and loaded with COPY INTO, whose load history skips
files already loaded, so re-running is safe. The ground-truth CSV is fully replaced.
"""
import os
from pathlib import Path

import snowflake.connector

LANDING = Path(__file__).resolve().parent.parent / "landing"


def copied_rows(cur):
    return sum(r[3] for r in cur.fetchall() if len(r) > 3 and r[1] in ("LOADED", "PARTIALLY_LOADED"))


def main():
    con = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        authenticator="SNOWFLAKE_JWT",
        private_key_file=os.environ["SNOWFLAKE_PRIVATE_KEY_PATH"],
        role=os.environ.get("SNOWFLAKE_ROLE", "LOADER"),
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "LOADING_WH"),
        database="RAW",
    )
    cur = con.cursor()
    try:
        for folder in sorted(p for p in LANDING.glob("*/*") if p.is_dir()):
            source, obj = folder.parent.name, folder.name
            stage = f"@RAW.PUBLIC.LANDING/{source}/{obj}/"
            cur.execute(f"PUT 'file://{folder.as_posix()}/*.jsonl' {stage} AUTO_COMPRESS=TRUE PARALLEL=8")
            cur.execute(f"""
                COPY INTO RAW.{source}.{obj} (RAW, _FILE, _FILE_ROW, _LOADED_AT)
                FROM (SELECT $1, METADATA$FILENAME, METADATA$FILE_ROW_NUMBER, CURRENT_TIMESTAMP() FROM {stage})
                FILE_FORMAT = (FORMAT_NAME = 'RAW.PUBLIC.JSONL')
            """)
            print(f"RAW.{source}.{obj}: {copied_rows(cur)} rows loaded")

        gt = LANDING / "ground_truth" / "mrr_monthly.csv"
        if gt.exists():
            stage = "@RAW.PUBLIC.LANDING/ground_truth/"
            cur.execute(f"PUT 'file://{gt.as_posix()}' {stage} AUTO_COMPRESS=TRUE OVERWRITE=TRUE")
            cur.execute("DELETE FROM RAW.GROUND_TRUTH.MRR_MONTHLY")
            cur.execute(f"COPY INTO RAW.GROUND_TRUTH.MRR_MONTHLY FROM {stage} "
                        "FILE_FORMAT = (FORMAT_NAME = 'RAW.PUBLIC.CSV_HEADER') FORCE = TRUE")
            print(f"RAW.GROUND_TRUTH.MRR_MONTHLY: {copied_rows(cur)} rows loaded (full replace)")
    finally:
        con.close()


if __name__ == "__main__":
    main()
