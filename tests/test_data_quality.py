import tempfile
import unittest
from pathlib import Path

from src.transformation.data_quality import validate_silver_csv


class TestSilverDataQuality(unittest.TestCase):
    def test_rejects_unexpected_quote_currency(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "invalid_silver.csv"
            csv_path.write_text(
                "rate_date,base_currency,quote_currency,exchange_rate\n"
                "2026-10-05,USD,XXX,1.234\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ValueError, "Silver data-quality checks failed"
            ):
                validate_silver_csv(csv_path)


if __name__ == "__main__":
    unittest.main()