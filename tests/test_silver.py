import csv
import json
import tempfile
import unittest
from pathlib import Path

from src.transformation.silver import build_silver


DATE = "2026-09-21"


class TestSilver(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

        root = Path(self.temp_dir.name)
        self.raw_root = root / "raw"
        self.silver_root = root / "silver"
        self.bronze_path = (
            self.raw_root / "2026" / "09" / "21" / "frankfurter_rates.json"
        )
        self.bronze_path.parent.mkdir(parents=True)

    def write_bronze(self, records):
        self.bronze_path.write_text(json.dumps(records), encoding="utf-8")

    def run_silver(self):
        return build_silver(DATE, self.raw_root, self.silver_root)

    def test_cleaning_and_identical_duplicate(self):
        self.write_bronze([
            {"date": DATE, "base": " usd ", "quote": " eur ", "rate": 0.87},
            {"date": DATE, "base": "USD", "quote": "EUR", "rate": 0.87},
            {"date": DATE, "base": "USD", "quote": "MYR", "rate": 4.078},
        ])

        path = self.run_silver()

        with path.open(newline="", encoding="utf-8") as file:
            rows = list(csv.DictReader(file))

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["base_currency"], "USD")
        self.assertEqual(rows[0]["quote_currency"], "EUR")
        self.assertEqual(rows[0]["exchange_rate"], "0.87")

    def test_conflicting_duplicate_fails(self):
        self.write_bronze([
            {"date": DATE, "base": "USD", "quote": "EUR", "rate": 0.87},
            {"date": DATE, "base": "USD", "quote": "EUR", "rate": 0.99},
        ])

        with self.assertRaisesRegex(ValueError, "Conflicting rates"):
            self.run_silver()

    def test_missing_rate_fails(self):
        self.write_bronze([
            {"date": DATE, "base": "USD", "quote": "EUR"},
        ])

        with self.assertRaisesRegex(ValueError, "missing required fields"):
            self.run_silver()

    def test_invalid_rate_fails(self):
        self.write_bronze([
            {"date": DATE, "base": "USD", "quote": "EUR", "rate": -1},
        ])

        with self.assertRaisesRegex(ValueError, "invalid currency or rate"):
            self.run_silver()


if __name__ == "__main__":
    unittest.main()
