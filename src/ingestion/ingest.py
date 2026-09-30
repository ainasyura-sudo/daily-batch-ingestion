import logging

from src.api.client import fetch_rates
from src.storage.bronze import save_bronze


logger = logging.getLogger(__name__)


def run_ingestion(processing_date: str) -> list[dict]:
	"""Fetch and persist the original Frankfurter response to Bronze."""
	raw_path = None

	def persist_response(content: bytes, source_url: str) -> None:
		nonlocal raw_path
		raw_path = save_bronze(processing_date, content, source_url)

	records = fetch_rates(processing_date, save_raw=persist_response)
	logger.info(
		"Bronze ingestion complete for %s: %d records saved to %s",
		processing_date,
		len(records),
		raw_path,
	)
	return records
