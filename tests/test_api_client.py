import logging
import unittest
from unittest.mock import Mock, patch

import requests

from src.api.client import fetch_rates


DATE = "2026-09-21"
VALID_RECORDS = [
    {"date": DATE, "base": "USD", "quote": "EUR", "rate": 0.87},
    {"date": DATE, "base": "USD", "quote": "GBP", "rate": 0.74},
    {"date": DATE, "base": "USD", "quote": "MYR", "rate": 4.07},
]


def mock_response(status, records=None, headers=None):
    response = Mock()
    response.status_code = status
    response.headers = headers or {}
    response.json.return_value = records
    response.raise_for_status.side_effect = (
        requests.HTTPError(response=response) if status >= 400 else None
    )
    return response


class TestApiClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Silence expected log output from intentional failure paths (e.g. retries
        # exhausted, temporary HTTP errors) so test output stays clean.
        logging.disable(logging.CRITICAL)

    @classmethod
    def tearDownClass(cls):
        logging.disable(logging.NOTSET)
    @patch("src.api.client.requests.get")
    def test_success(self, get):
        get.return_value = mock_response(200, VALID_RECORDS)

        self.assertEqual(len(fetch_rates(DATE)), 3)
        self.assertEqual(get.call_count, 1)

    @patch("src.api.client.time.sleep")
    @patch("src.api.client.requests.get")
    def test_429_respects_retry_after(self, get, sleep):
        get.side_effect = [
            mock_response(429, headers={"Retry-After": "5"}),
            mock_response(200, VALID_RECORDS),
        ]

        self.assertEqual(len(fetch_rates(DATE)), 3)
        self.assertEqual(get.call_count, 2)
        sleep.assert_called_once_with(5.0)

    @patch("src.api.client.time.sleep")
    @patch("src.api.client.requests.get")
    def test_500_retries_then_succeeds(self, get, sleep):
        get.side_effect = [mock_response(500), mock_response(200, VALID_RECORDS)]

        self.assertEqual(len(fetch_rates(DATE)), 3)
        self.assertEqual(get.call_count, 2)
        sleep.assert_called_once()

    @patch("src.api.client.time.sleep")
    @patch("src.api.client.requests.get")
    def test_timeout_fails_after_four_attempts(self, get, sleep):
        get.side_effect = requests.Timeout("Timed out")

        with self.assertRaises(RuntimeError):
            fetch_rates(DATE)

        self.assertEqual(get.call_count, 4)
        self.assertEqual(sleep.call_count, 3)

    @patch("src.api.client.requests.get")
    def test_missing_field_fails(self, get):
        bad_records = [record.copy() for record in VALID_RECORDS]
        del bad_records[0]["rate"]
        get.return_value = mock_response(200, bad_records)

        with self.assertRaises(ValueError):
            fetch_rates(DATE)


if __name__ == "__main__":
    unittest.main()