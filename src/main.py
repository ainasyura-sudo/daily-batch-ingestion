import argparse
import logging
import os
from datetime import datetime
from time import perf_counter
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from src.database import initialize_database
from src.ingestion.ingest import run_ingestion
from src.observability import configure_logging
from src.transformation.gold import build_gold
from src.transformation.silver import build_silver


logger = logging.getLogger(__name__)


def main() -> int:
    load_dotenv()
    configure_logging()

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
        help="Skip the Gold layer",
    )
    args = parser.parse_args()

    processing_date = args.date or datetime.now(
        ZoneInfo("Asia/Kuala_Lumpur")
    ).date().isoformat()

    started = perf_counter()
    stage = "ingestion"
    metrics = {"processing_date": processing_date}

    logger.info(
        "Pipeline started",
        extra={"fields": {
            **metrics,
            "event": "pipeline_started",
        }},
    )

    try:
        stage_started = perf_counter()
        records = run_ingestion(processing_date)
        metrics["records_fetched"] = len(records)
        metrics["ingestion_seconds"] = round(
            perf_counter() - stage_started, 3
        )

        stage = "silver"
        stage_started = perf_counter()
        silver_path = build_silver(processing_date)
        metrics["silver_seconds"] = round(
            perf_counter() - stage_started, 3
        )
        metrics["silver_path"] = str(silver_path)

        if not args.skip_gold:
            stage = "database_initialization"
            stage_started = perf_counter()

            if os.getenv(
                "DB_INITIALIZE", "false"
            ).strip().lower() == "true":
                initialize_database()

            metrics["database_initialization_seconds"] = round(
                perf_counter() - stage_started, 3
            )

            stage = "gold"
            stage_started = perf_counter()
            metrics["fact_rows_inserted"] = build_gold(
                processing_date
            )
            metrics["gold_seconds"] = round(
                perf_counter() - stage_started, 3
            )

        metrics["gold_skipped"] = args.skip_gold
        metrics["pipeline_seconds"] = round(
            perf_counter() - started, 3
        )

        logger.info(
            "Pipeline completed",
            extra={"fields": {
                **metrics,
                "event": "pipeline_completed",
                "status": "success",
            }},
        )
        return 0

    except Exception:
        metrics["pipeline_seconds"] = round(
            perf_counter() - started, 3
        )

        logger.exception(
            "Pipeline failed",
            extra={"fields": {
                **metrics,
                "event": "pipeline_failed",
                "status": "failed",
                "failed_stage": stage,
            }},
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())