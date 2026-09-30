import argparse
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from src.database import initialize_database
from src.ingestion.ingest import run_ingestion
from src.transformation.gold import build_gold
from src.transformation.silver import build_silver


def main() -> None:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Fetch daily exchange rates"
    )
    parser.add_argument(
        "--date",
        help="Processing date in YYYY-MM-DD format (default: today in Malaysia)",
    )
    parser.add_argument(
        "--skip-gold",
        action="store_true",
        help="Skip the gold layer load when SQL Server is unavailable",
    )
    args = parser.parse_args()

    processing_date = args.date or datetime.now(
        ZoneInfo("Asia/Kuala_Lumpur")
    ).date().isoformat()

    logging.info("Processing date: %s", processing_date)

    records = run_ingestion(processing_date)

    silver_path = build_silver(processing_date)
    print(f"Silver data saved to: {silver_path}")

    if not args.skip_gold:
        if os.getenv("DB_INITIALIZE", "false").strip().lower() == "true":
            logging.info("Initializing database and Gold schema")
            initialize_database()

        inserted = build_gold(processing_date)
        print(f"Gold layer: {inserted} fact row(s) loaded into SQL Server")

    print(f"Fetched {len(records)} exchange-rate records:")
    for record in records:
        print(record)


if __name__ == "__main__":
    main()