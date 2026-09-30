import json
from datetime import datetime, timezone
from pathlib import Path


RAW_ROOT = Path("data/raw")


def save_bronze(
    processing_date: str,
    raw_content: bytes,
    source_url: str,
) -> Path:
    year, month, day = processing_date.split("-")
    folder = RAW_ROOT / year / month / day
    folder.mkdir(parents=True, exist_ok=True)

    raw_path = folder / "frankfurter_rates.json"
    metadata_path = folder / "metadata.json"

    # Save the API response exactly as received.
    raw_path.write_bytes(raw_content)

    metadata = {
        "processing_date": processing_date,
        "ingested_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_url": source_url,
        "raw_file": raw_path.name,
    }
    metadata_path.write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )

    return raw_path
