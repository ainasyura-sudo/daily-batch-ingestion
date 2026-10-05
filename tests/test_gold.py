import csv
import logging
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from src.transformation.gold import (
    _date_attributes,
    _insert_fact,
    _upsert_dim_currency,
    _upsert_dim_date,
    build_gold,
)


DATE = "2026-09-21"

# ---------------------------------------------------------------------------
# Silver CSV helpers
# ---------------------------------------------------------------------------

def _write_silver(directory: Path, rows: list[dict]) -> Path:
    """Write a minimal silver CSV under directory/2026/09/21/exchange_rates.csv."""
    year, month, day = DATE.split("-")
    path = directory / year / month / day / "exchange_rates.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["rate_date", "base_currency", "quote_currency", "exchange_rate"],
        )
        writer.writeheader()
        writer.writerows(rows)
    return path


_SILVER_ROWS = [
    {"rate_date": DATE, "base_currency": "USD", "quote_currency": "EUR", "exchange_rate": "0.870000"},
    {"rate_date": DATE, "base_currency": "USD", "quote_currency": "GBP", "exchange_rate": "0.740000"},
    {"rate_date": DATE, "base_currency": "USD", "quote_currency": "MYR", "exchange_rate": "4.070000"},
]


def _make_conn(insert_action: str | None= "INSERT") -> MagicMock:
    """Return a mock pyodbc connection whose cursor behaves sensibly."""
    cursor = MagicMock()
    # _upsert_dim_currency does cursor.fetchone() → (currency_id,)
    # _insert_fact does cursor.fetchone() → (action_string,)
    # We must alternate return values across multiple fetchone() calls.
    # Use side_effect list: currency upserts return (1,) ids; fact returns action.
    cursor.fetchone.side_effect = [
        (1,),            # USD currency_id
        (2,),            # EUR currency_id
        (3,),            # GBP currency_id
        (4,),            # MYR currency_id
        (insert_action,) if insert_action is not None else None,
        (insert_action,) if insert_action is not None else None,
        (insert_action,) if insert_action is not None else None,
    ]
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn


# ===========================================================================
# Unit tests
# ===========================================================================

class TestDateAttributes(unittest.TestCase):
    """_date_attributes returns correct calendar fields for a known date."""

    def test_weekday_date(self):
        # 2026-09-21 is a Monday
        attrs = _date_attributes(__import__("datetime").date(2026, 9, 21))
        self.assertEqual(attrs["date_id"], 20260921)
        self.assertEqual(attrs["year"], 2026)
        self.assertEqual(attrs["quarter"], 3)
        self.assertEqual(attrs["month"], 9)
        self.assertEqual(attrs["month_name"], "September")
        self.assertEqual(attrs["day"], 21)
        self.assertEqual(attrs["day_name"], "Monday")
        self.assertEqual(attrs["is_weekend"], 0)

    def test_weekend_date(self):
        # 2026-09-20 is a Sunday
        attrs = _date_attributes(__import__("datetime").date(2026, 9, 20))
        self.assertEqual(attrs["day_name"], "Sunday")
        self.assertEqual(attrs["is_weekend"], 1)


class TestInverseRate(unittest.TestCase):
    """_insert_fact computes the correct inverse rate."""

    def test_inverse_rate_value(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = ("INSERT",)

        rate = Decimal("0.87")
        _insert_fact(cursor, date_id=20260921, base_id=1, quote_id=2, exchange_rate=rate)

        # The second positional parameter in the execute call after date_id,
        # base_id, quote_id, exchange_rate is inverse_rate.
        args = cursor.execute.call_args[0][1:]  # skip SQL string
        # args: (date_id, base_id, quote_id, exchange_rate_str, inverse_rate_str)
        inverse = Decimal(args[4])
        expected = Decimal(1) / Decimal("0.87")
        self.assertAlmostEqual(float(inverse), float(expected), places=6)


class TestBuildGold(unittest.TestCase):
    """build_gold() reads Silver CSV and calls the correct SQL operations."""

    @classmethod
    def setUpClass(cls):
        logging.disable(logging.CRITICAL)

    @classmethod
    def tearDownClass(cls):
        logging.disable(logging.NOTSET)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.silver_root = Path(self.temp.name) / "silver"
        _write_silver(self.silver_root, _SILVER_ROWS)

    def test_inserts_correct_row_count(self):
        conn = _make_conn(insert_action="INSERT")
        result = build_gold(DATE, silver_root=self.silver_root, conn=conn)
        self.assertEqual(result, 3)

    def test_skips_already_present_rows(self):
        conn = _make_conn(insert_action=None)
        result = build_gold(
            DATE,
            silver_root=self.silver_root,
            conn=conn,
        )

        self.assertEqual(result, 0)
        conn.commit.assert_called_once()
        conn.rollback.assert_not_called()

    def test_updates_are_not_counted_as_inserts(self):
        conn = _make_conn(insert_action="UPDATE")
        result = build_gold(
            DATE,
            silver_root=self.silver_root,
            conn=conn,
        )

        self.assertEqual(result, 0)
        conn.commit.assert_called_once()
        conn.rollback.assert_not_called()

    def test_missing_silver_raises_file_not_found(self):
        conn = MagicMock()
        with self.assertRaises(FileNotFoundError):
            build_gold("2025-01-01", silver_root=self.silver_root, conn=conn)

    def test_commit_called_on_success(self):
        conn = _make_conn()
        build_gold(DATE, silver_root=self.silver_root, conn=conn)
        conn.commit.assert_called_once()
        conn.rollback.assert_not_called()

    def test_rollback_on_error(self):
        conn = MagicMock()
        cursor = MagicMock()
        cursor.execute.side_effect = RuntimeError("DB error")
        conn.cursor.return_value = cursor

        with self.assertRaises(RuntimeError):
            build_gold(DATE, silver_root=self.silver_root, conn=conn)

        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()

    def test_empty_silver_returns_zero(self):
        empty_root = Path(self.temp.name) / "empty_silver"
        _write_silver(empty_root, [])  # header only
        conn = MagicMock()
        result = build_gold(DATE, silver_root=empty_root, conn=conn)
        self.assertEqual(result, 0)
        conn.cursor.assert_not_called()  # nothing loaded → no DB work


if __name__ == "__main__":
    unittest.main()
