import csv
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from src.transformation.data_quality import validate_silver_csv


REQUIRED_FIELDS = {"date", "base", "quote", "rate"}


def build_silver(
    processing_date: str,
    raw_root: Path = Path("data/raw"),
    silver_root: Path = Path("data/silver"),
) -> Path:
    year, month, day = processing_date.split("-")
    bronze_path = raw_root / year / month / day / "frankfurter_rates.json"
    silver_path = silver_root / year / month / day / "exchange_rates.csv"

    # Read from Bronze, not directly from the API.
    with bronze_path.open("r", encoding="utf-8") as file:
        records = json.load(file)

    if not isinstance(records, list) or not records:
        raise ValueError("Bronze data must contain a non-empty list")

    cleaned = {}

    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict) or not REQUIRED_FIELDS.issubset(record):
            raise ValueError(f"Record {index}: missing required fields")

        try:
            rate_date = date.fromisoformat(str(record["date"]))
            rate = Decimal(str(record["rate"]))
        except (ValueError, InvalidOperation) as exc:
            raise ValueError(f"Record {index}: invalid date or rate") from exc

        base = str(record["base"]).strip().upper()
        quote = str(record["quote"]).strip().upper()

        if not base or not quote or not rate.is_finite() or rate <= 0:
            raise ValueError(f"Record {index}: invalid currency or rate")

        if rate_date.isoformat() != processing_date:
            raise ValueError(f"Record {index}: unexpected date")

        # One rate for each date, base currency, and quote currency.
        key = (rate_date.isoformat(), base, quote)
        row = {
            "rate_date": rate_date.isoformat(),
            "base_currency": base,
            "quote_currency": quote,
            "exchange_rate": str(rate),
        }

        if key in cleaned and cleaned[key] != row:
            raise ValueError(f"Conflicting rates for {key}")

        cleaned[key] = row  # Identical duplicates collapse into one row.

    silver_path.parent.mkdir(parents=True, exist_ok=True)

    with silver_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "rate_date",
                "base_currency",
                "quote_currency",
                "exchange_rate",
            ],
        )
        writer.writeheader()
        writer.writerows(cleaned[key] for key in sorted(cleaned))

    validate_silver_csv(silver_path)

    return silver_path