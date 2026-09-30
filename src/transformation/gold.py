"""
src/transformation/gold.py
Gold layer: load cleaned Silver CSV into the SQL Server star schema.

Tables written (in dependency order):
    gold.dim_date          -- calendar attributes for the processing date
    gold.dim_currency      -- ISO 4217 currency lookup (upsert)
    gold.fact_exchange_rate -- one row per (date, base, quote)
"""

import csv
import logging
from datetime import date
from decimal import Decimal
from pathlib import Path

import pyodbc


logger = logging.getLogger(__name__)

# Static currency name lookup. Extended currencies are accepted but named
# 'Unknown' until a proper seed is added to 02_seed_dim_currency.sql.
_CURRENCY_NAMES: dict[str, str] = {
    "EUR": "Euro",
    "GBP": "British Pound Sterling",
    "MYR": "Malaysian Ringgit",
    "USD": "US Dollar",
}

# Day-of-week names indexed by Python's weekday() (0=Monday … 6=Sunday).
_DOW_NAMES = (
    "Monday", "Tuesday", "Wednesday", "Thursday",
    "Friday", "Saturday", "Sunday",
)

# SQL Server DATEFIRST 7: 1=Sunday … 7=Saturday
_PYTHON_DOW_TO_SSAS = {0: 2, 1: 3, 2: 4, 3: 5, 4: 6, 5: 7, 6: 1}

_MONTH_NAMES = (
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _date_attributes(d: date) -> dict:
    """Return a dict of dim_date column values for a given date."""
    ss_dow = _PYTHON_DOW_TO_SSAS[d.weekday()]  # 1=Sun … 7=Sat
    is_weekend = d.weekday() >= 5              # Saturday=5, Sunday=6
    return {
        "date_id":     int(d.strftime("%Y%m%d")),
        "rate_date":   d.isoformat(),
        "year":        d.year,
        "quarter":     (d.month - 1) // 3 + 1,
        "month":       d.month,
        "month_name":  _MONTH_NAMES[d.month],
        "day":         d.day,
        "day_of_week": ss_dow,
        "day_name":    _DOW_NAMES[d.weekday()],
        "is_weekend":  1 if is_weekend else 0,
    }


def _upsert_dim_date(cursor: pyodbc.Cursor, attrs: dict) -> int:
    """Upsert a dim_date row and return its date_id."""
    cursor.execute(
        """
        MERGE gold.dim_date AS t
        USING (SELECT
            ? AS date_id, ? AS rate_date, ? AS [year], ? AS quarter,
            ? AS [month], ? AS month_name, ? AS [day],
            ? AS day_of_week, ? AS day_name, ? AS is_weekend
        ) AS s
        ON t.date_id = s.date_id
        WHEN NOT MATCHED BY TARGET THEN
            INSERT (date_id, rate_date, [year], quarter, [month], month_name,
                    [day], day_of_week, day_name, is_weekend)
            VALUES (s.date_id, s.rate_date, s.[year], s.quarter, s.[month],
                    s.month_name, s.[day], s.day_of_week, s.day_name, s.is_weekend);
        """,
        attrs["date_id"], attrs["rate_date"], attrs["year"], attrs["quarter"],
        attrs["month"], attrs["month_name"], attrs["day"],
        attrs["day_of_week"], attrs["day_name"], attrs["is_weekend"],
    )
    return attrs["date_id"]


def _upsert_dim_currency(cursor: pyodbc.Cursor, code: str) -> int:
    """Insert a currency if needed and return its currency_id."""
    name = _CURRENCY_NAMES.get(code, "Unknown")

    cursor.execute(
        """
        MERGE gold.dim_currency AS t
        USING (SELECT ? AS currency_code, ? AS currency_name) AS s
        ON t.currency_code = s.currency_code
        WHEN NOT MATCHED BY TARGET THEN
            INSERT (currency_code, currency_name)
            VALUES (s.currency_code, s.currency_name);
        """,
        code, name,
    )

    cursor.execute(
        "SELECT currency_id FROM gold.dim_currency WHERE currency_code = ?",
        code,
    )
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError(f"Currency ID not found for {code}")
    return row[0]


def _insert_fact(
    cursor: pyodbc.Cursor,
    date_id: int,
    base_id: int,
    quote_id: int,
    exchange_rate: Decimal,
) -> int:
    """
    Insert one fact row using MERGE to skip existing (date, base, quote)
    combinations (idempotent re-runs).  Returns 1 if inserted, 0 if skipped.
    """
    inverse_rate = Decimal(1) / exchange_rate

    cursor.execute(
        """
        MERGE gold.fact_exchange_rate AS t
        USING (
            SELECT ? AS date_id,
                   ? AS base_currency_id,
                   ? AS quote_currency_id,
                   ? AS exchange_rate,
                   ? AS inverse_rate
        ) AS s
        ON  t.date_id           = s.date_id
        AND t.base_currency_id  = s.base_currency_id
        AND t.quote_currency_id = s.quote_currency_id
        WHEN NOT MATCHED BY TARGET THEN
            INSERT (date_id, base_currency_id, quote_currency_id,
                    exchange_rate, inverse_rate)
            VALUES (s.date_id, s.base_currency_id, s.quote_currency_id,
                    s.exchange_rate, s.inverse_rate)
        OUTPUT $action;
        """,
        date_id, base_id, quote_id,
        str(exchange_rate), str(inverse_rate),
    )
    row = cursor.fetchone()
    return 1 if row and row[0] == "INSERT" else 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_gold(
    processing_date: str,
    silver_root: Path = Path("data/silver"),
    conn: pyodbc.Connection | None = None,
) -> int:
    """
    Load the Silver CSV for *processing_date* into the SQL Server gold schema.

    Parameters
    ----------
    processing_date : str
        Date in 'YYYY-MM-DD' format.
    silver_root : Path
        Root directory of silver CSVs (default: data/silver).
    conn : pyodbc.Connection | None
        An open pyodbc connection.  If None, ``src.database.get_connection()``
        is called automatically — requires DB_* environment variables.

    Returns
    -------
    int
        Number of fact rows inserted (0 if all were already present).

    Raises
    ------
    FileNotFoundError
        If the Silver CSV for the given date does not exist.
    ValueError
        If the Silver CSV contains invalid data.
    RuntimeError
        If the database connection cannot be established.
    """
    rate_date = date.fromisoformat(processing_date)
    year, month, day = processing_date.split("-")
    silver_path = silver_root / year / month / day / "exchange_rates.csv"

    if not silver_path.exists():
        raise FileNotFoundError(
            f"Silver file not found: {silver_path}. "
            "Run the silver transformation first."
        )

    # Read Silver CSV
    with silver_path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    if not rows:
        logger.warning("Silver file is empty for %s — nothing loaded to gold", processing_date)
        return 0

    # Obtain connection
    _owns_conn = conn is None
    if conn is None:
        from src.database import get_connection  # noqa: PLC0415 — lazy import
        conn = get_connection()

    inserted = 0

    try:
        cursor = conn.cursor()

        # 1. dim_date
        date_attrs = _date_attributes(rate_date)
        date_id = _upsert_dim_date(cursor, date_attrs)
        logger.info("dim_date upserted: date_id=%d (%s)", date_id, processing_date)

        # 2. dim_currency (collect unique codes first)
        currency_ids: dict[str, int] = {}
        for row in rows:
            for code in (row["base_currency"], row["quote_currency"]):
                if code not in currency_ids:
                    currency_ids[code] = _upsert_dim_currency(cursor, code)
        logger.info("dim_currency upserted: %s", sorted(currency_ids))

        # 3. fact_exchange_rate
        for row in rows:
            try:
                rate = Decimal(row["exchange_rate"])
            except Exception as exc:
                raise ValueError(
                    f"Invalid exchange_rate in silver row: {row}"
                ) from exc

            base_id  = currency_ids[row["base_currency"]]
            quote_id = currency_ids[row["quote_currency"]]
            inserted += _insert_fact(cursor, date_id, base_id, quote_id, rate)

        conn.commit()
        logger.info(
            "Gold load complete for %s: %d/%d fact rows inserted",
            processing_date, inserted, len(rows),
        )

    except Exception:
        conn.rollback()
        raise

    finally:
        if _owns_conn:
            conn.close()

    return inserted
