"""Date planning helpers for incremental loads and historical backfills."""

from collections.abc import Iterator
from datetime import date, timedelta


def processing_dates(start_date: str, end_date: str) -> Iterator[str]:
    """Return weekdays between the dates, including start and end."""
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)

    if end < start:
        raise ValueError("end_date must be on or after start_date")

    current = start
    while current <= end:
        if current.weekday() < 5:
            yield current.isoformat()
        current += timedelta(days=1)


def incremental_dates(
    last_successful_date: date | None,
    end_date: str,
    pending_date: date | None = None,
) -> list[str]:
    """Plan dates after the watermark through end_date."""
    end = date.fromisoformat(end_date)

    if pending_date:
        start = pending_date
    elif last_successful_date:
        start = last_successful_date + timedelta(days=1)
    else:
        # If no watermark exists yet, process the end date.
        start = end

    if start > end:
        return []

    return list(processing_dates(start.isoformat(), end.isoformat()))