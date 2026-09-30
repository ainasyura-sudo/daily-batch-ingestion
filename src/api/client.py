import logging
import time
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime

import requests


API_URL = "https://api.frankfurter.dev/v2/rates"
QUOTES = {"EUR", "GBP", "MYR"}
MAX_ATTEMPTS = 4  # First request + up to 3 retries
logger = logging.getLogger(__name__)


def retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None

    try:
        return max(0.0, float(value))
    except ValueError:
        pass

    try:
        retry_at = parsedate_to_datetime(value)
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        logger.warning("Invalid Retry-After header: %s", value)
        return None


def fetch_rates(processing_date: str, save_raw=None) -> list[dict]:
    date.fromisoformat(processing_date)

    params = {
        "date": processing_date,
        "base": "USD",
        "quotes": ",".join(sorted(QUOTES)),
    }

    for attempt in range(1, MAX_ATTEMPTS + 1):
        retry_after = None
        logger.info("API attempt %d/%d for %s", attempt, MAX_ATTEMPTS, processing_date)

        try:
            response = requests.get(API_URL, params=params, timeout=(5, 15))
            response.raise_for_status()

            try:
                records = response.json()
            except requests.exceptions.JSONDecodeError as exc:
                raise ValueError("API returned malformed JSON") from exc

            if not isinstance(records, list) or not records:
                raise ValueError("API returned an empty or invalid records list")

            required_fields = {"date", "base", "quote", "rate"}
            found_quotes = set()

            for record in records:
                if not isinstance(record, dict) or not required_fields.issubset(record):
                    raise ValueError(f"API record has missing fields: {record}")

                if record["date"] != processing_date or record["base"] != "USD":
                    raise ValueError(f"Unexpected date or base currency: {record}")

                if record["quote"] not in QUOTES:
                    raise ValueError(f"Unexpected quote currency: {record}")

                if (
                    not isinstance(record["rate"], (int, float))
                    or isinstance(record["rate"], bool)
                ):
                    raise ValueError(f"Invalid exchange rate: {record}")

                if record["quote"] in found_quotes:
                    raise ValueError(f"Duplicate quote currency: {record['quote']}")
                found_quotes.add(record["quote"])

            if found_quotes != QUOTES:
                raise ValueError(f"Missing currencies: {sorted(QUOTES - found_quotes)}")

            if save_raw is not None:
                save_raw(response.content, response.url)

            logger.info("SUCCESS: received %d records", len(records))
            return records

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            logger.warning("Temporary connection failure: %s", exc)

        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code

            if status != 429 and not 500 <= status <= 599:
                logger.error("Permanent HTTP error %d", status)
                raise

            logger.warning("Temporary HTTP error %d", status)

            if status == 429:
                retry_after = retry_after_seconds(exc.response.headers.get("Retry-After"))

        if attempt == MAX_ATTEMPTS:
            logger.error("FAILED: API request exhausted %d attempts", MAX_ATTEMPTS)
            raise RuntimeError(
                f"API request did not succeed after {MAX_ATTEMPTS} attempts"
            )

        delay = min(2 ** (attempt - 1), 8)

        if retry_after is not None:
            delay = max(delay, retry_after)

        delay = min(delay, 30)
        logger.info("Retrying in %.1f seconds", delay)
        time.sleep(delay)

    raise RuntimeError("API request failed")