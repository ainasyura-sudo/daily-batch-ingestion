import argparse
import logging
import os
from datetime import date, datetime
from time import perf_counter
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from src.database import (
    advance_watermark,
    get_pending_date,
    get_watermark,
    initialize_database,
    mark_pending_date,
)
from src.ingestion.ingest import run_ingestion
from src.observability import configure_logging
from src.orchestration import incremental_dates, processing_dates
from src.transformation.gold import build_gold
from src.transformation.silver import build_silver


logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch daily exchange rates"
    )
    parser.add_argument(
        "--date",
        help="Process one date in YYYY-MM-DD format",
    )
    parser.add_argument(
        "--start-date",
        help="First date for a historical backfill (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end-date",
        help="Last backfill date, or limit for --incremental",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Load weekdays after the watermark through today or --end-date",
    )
    parser.add_argument(
        "--skip-gold",
        action="store_true",
        help="Skip loading data into Gold",
    )
    args = parser.parse_args()

    if args.date and (args.start_date or args.end_date or args.incremental):
        parser.error("--date cannot be combined with range or incremental options")
    if args.start_date and args.incremental:
        parser.error("--start-date cannot be combined with --incremental")
    if bool(args.start_date) != bool(args.end_date) and not (
        args.incremental and not args.start_date
    ):
        parser.error("backfill needs both --start-date and --end-date")
    if args.end_date and not (args.start_date or args.incremental):
        parser.error("--end-date requires --start-date or --incremental")
    if args.incremental and args.skip_gold:
        parser.error("--incremental requires Gold loading")

    try:
        for value in (args.date, args.start_date, args.end_date):
            if value:
                date.fromisoformat(value)
    except ValueError as exc:
        parser.error(f"Use dates in YYYY-MM-DD format: {exc}")

    return args


def _resolve_dates(args: argparse.Namespace, today: str) -> list[str]:
    if args.date:
        return [args.date]

    if args.start_date:
        return list(processing_dates(args.start_date, args.end_date))

    if args.incremental:
        return incremental_dates(
            get_watermark(),
            args.end_date or today,
            pending_date=get_pending_date(),
        )

    return [today]


def main() -> int:
    load_dotenv()
    configure_logging()
    args = _parse_args()

    today = datetime.now(
        ZoneInfo("Asia/Kuala_Lumpur")
    ).date().isoformat()

    started = perf_counter()
    stage = "database_initialization"
    current_date: str | None = None
    metrics: dict = {
        "requested_date": args.date,
        "incremental": args.incremental,
    }

    try:
        initialization_seconds = 0.0
        if not args.skip_gold and os.getenv(
            "DB_INITIALIZE", "false"
        ).strip().lower() == "true":
            stage_started = perf_counter()
            initialize_database()
            initialization_seconds = round(
                perf_counter() - stage_started, 3
            )

        stage = "date_planning"
        dates = _resolve_dates(args, today)

        if args.start_date:
            metrics.update({
                "start_date": args.start_date,
                "end_date": args.end_date,
            })
        elif args.incremental:
            metrics["end_date"] = args.end_date or today
        elif dates:
            metrics["processing_date"] = dates[0]

        logger.info(
            "Pipeline started",
            extra={"fields": {
                **metrics,
                "planned_dates": len(dates),
                "event": "pipeline_started",
            }},
        )

        records_total = 0
        inserted_total = 0
        completed_dates: list[str] = []

        for current_date in dates:
            date_started = perf_counter()
            date_metrics: dict = {"processing_date": current_date}

            if not args.skip_gold:
                stage = "watermark"
                mark_pending_date(current_date)

            stage = "ingestion"
            stage_started = perf_counter()
            records = run_ingestion(current_date)
            date_metrics["records_fetched"] = len(records)
            date_metrics["ingestion_seconds"] = round(
                perf_counter() - stage_started, 3
            )
            records_total += len(records)

            stage = "silver"
            stage_started = perf_counter()
            silver_path = build_silver(current_date)
            date_metrics["silver_seconds"] = round(
                perf_counter() - stage_started, 3
            )
            date_metrics["silver_path"] = str(silver_path)

            if not args.skip_gold:
                stage = "gold"
                stage_started = perf_counter()
                inserted = build_gold(current_date)
                date_metrics["fact_rows_inserted"] = inserted
                date_metrics["gold_seconds"] = round(
                    perf_counter() - stage_started, 3
                )
                inserted_total += inserted

                stage = "watermark"
                advance_watermark(current_date)
                date_metrics["watermark_date"] = current_date

            date_metrics["date_pipeline_seconds"] = round(
                perf_counter() - date_started, 3
            )
            completed_dates.append(current_date)

            logger.info(
                "Processing date completed",
                extra={"fields": {
                    **date_metrics,
                    "event": "processing_date_completed",
                    "status": "success",
                }},
            )

        metrics.update({
            "processed_dates": completed_dates,
            "date_count": len(completed_dates),
            "records_fetched": records_total,
            "fact_rows_inserted": inserted_total,
            "database_initialization_seconds": initialization_seconds,
            "gold_skipped": args.skip_gold,
            "pipeline_seconds": round(perf_counter() - started, 3),
        })

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
        metrics.update({
            "failed_date": current_date,
            "failed_stage": stage,
            "pipeline_seconds": round(perf_counter() - started, 3),
        })
        logger.exception(
            "Pipeline failed",
            extra={"fields": {
                **metrics,
                "event": "pipeline_failed",
                "status": "failed",
            }},
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())