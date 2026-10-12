import unittest
from datetime import date

from src.orchestration import incremental_dates, processing_dates


class TestDatePlanning(unittest.TestCase):
    def test_backfill_includes_dates_and_skips_weekends(self):
        self.assertEqual(
            list(processing_dates("2026-10-02", "2026-10-06")),
            ["2026-10-02", "2026-10-05", "2026-10-06"],
        )

    def test_incremental_starts_after_watermark(self):
        self.assertEqual(
            incremental_dates(date(2026, 10, 2), "2026-10-06"),
            ["2026-10-05", "2026-10-06"],
        )

    def test_no_watermark_processes_end_date_only(self):
        self.assertEqual(
            incremental_dates(None, "2026-10-07"),
            ["2026-10-07"],
        )

    def test_incremental_retries_pending_date_first(self):
        self.assertEqual(
            incremental_dates(
                date(2026, 10, 6),
                "2026-10-08",
                pending_date=date(2026, 10, 7),
            ),
            ["2026-10-07", "2026-10-08"],
        )

    def test_incremental_is_empty_when_watermark_is_current(self):
        self.assertEqual(
            incremental_dates(date(2026, 10, 7), "2026-10-07"),
            [],
        )

    def test_rejects_reversed_backfill_range(self):
        with self.assertRaisesRegex(ValueError, "on or after"):
            list(processing_dates("2026-10-07", "2026-10-06"))


if __name__ == "__main__":
    unittest.main()