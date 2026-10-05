import logging
import time
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from time import perf_counter

import requests


API_URL = "https://api.frankfurter.dev/v2/rates"
QUOTES = {"EUR", "GBP", "MYR"}
MAX_ATTEMPTS = 4
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

        return max(
            0.0,
            (retry_at - datetime.now(timezone.utc)).total_seconds(),
        )
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

    api_request_seconds = 0.0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        retry_after = None

        logger.info(
            "API attempt %d/%d for %s",
            attempt,
            MAX_ATTEMPTS,
            processing_date,
        )

        try:
            response = None
            request_started = perf_counter()

            try:
                response = requests.get(
                    API_URL,
                    params=params,
                    timeout=(5, 15),
                )
            finally:
                request_seconds = perf_counter() - request_started
                api_request_seconds += request_seconds

                logger.info(
                    "API request finished",
                    extra={"fields": {
                        "event": "api_request_finished",
                        "processing_date": processing_date,
                        "attempt": attempt,
                        "request_seconds": round(request_seconds, 3),
                        "http_status": (
                            response.status_code
                            if response is not None
                            else None
                        ),
                    }},
                )

            response.raise_for_status()

            try:
                records = response.json()
            except requests.exceptions.JSONDecodeError as exc:
                raise ValueError("API returned malformed JSON") from exc

            if not isinstance(records, list) or not records:
                raise ValueError(
                    "API returned an empty or invalid records list"
                )

            required_fields = {"date", "base", "quote", "rate"}
            found_quotes = set()

            for record in records:
                if (
                    not isinstance(record, dict)
                    or not required_fields.issubset(record)
                ):
                    raise ValueError(
                        f"API record has missing fields: {record}"
                    )

                if (
                    record["date"] != processing_date
                    or record["base"] != "USD"
                ):
                    raise ValueError(
                        f"Unexpected date or base currency: {record}"
                    )

                if record["quote"] not in QUOTES:
                    raise ValueError(
                        f"Unexpected quote currency: {record}"
                    )

                if (
                    not isinstance(record["rate"], (int, float))
                    or isinstance(record["rate"], bool)
                ):
                    raise ValueError(
                        f"Invalid exchange rate: {record}"
                    )

                if record["quote"] in found_quotes:
                    raise ValueError(
                        f"Duplicate quote currency: {record['quote']}"
                    )

                found_quotes.add(record["quote"])

            if found_quotes != QUOTES:
                raise ValueError(
                    f"Missing currencies: {sorted(QUOTES - found_quotes)}"
                )

            if save_raw is not None:
                save_raw(response.content, response.url)

            logger.info(
                "API fetch completed",
                extra={"fields": {
                    "event": "api_fetch_completed",
                    "processing_date": processing_date,
                    "records_received": len(records),
                    "api_attempts": attempt,
                    "api_retries": attempt - 1,
                    "api_request_seconds": round(
                        api_request_seconds, 3
                    ),
                }},
            )
            return records

        except (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
        ) as exc:
            logger.warning("Temporary connection failure: %s", exc)

        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code

            if status != 429 and not 500 <= status <= 599:
                logger.error("Permanent HTTP error %d", status)
                raise

            logger.warning("Temporary HTTP error %d", status)

            if status == 429:
                retry_after = retry_after_seconds(
                    exc.response.headers.get("Retry-After")
                )

        if attempt == MAX_ATTEMPTS:
            logger.error(
                "API request exhausted all attempts",
                extra={"fields": {
                    "event": "api_retries_exhausted",
                    "processing_date": processing_date,
                    "api_attempts": attempt,
                    "api_retries": attempt - 1,
                    "api_request_seconds": round(
                        api_request_seconds, 3
                    ),
                }},
            )
            raise RuntimeError(
                f"API request did not succeed after "
                f"{MAX_ATTEMPTS} attempts"
            )

        delay = min(2 ** (attempt - 1), 8)

        if retry_after is not None:
            delay = max(delay, retry_after)

        delay = min(delay, 30)

        logger.info(
            "Retrying API request",
            extra={"fields": {
                "event": "api_retry_scheduled",
                "processing_date": processing_date,
                "next_attempt": attempt + 1,
                "retry_delay_seconds": delay,
            }},
        )
        time.sleep(delay)

    raise RuntimeError("API request failed")