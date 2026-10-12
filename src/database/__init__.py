"""
src/database/__init__.py
Database connection factory for the gold layer.

Required environment variables (set in .env or the shell):
    DB_SERVER   -- SQL Server host, e.g. "localhost" or "myserver.database.windows.net"
    DB_NAME     -- Database name, e.g. "fx_pipeline"
    DB_USER     -- SQL Server login name
    DB_PASSWORD -- SQL Server login password
    DB_DRIVER   -- (optional) ODBC driver name; auto-detected if omitted
"""

import os
import re
import time
from datetime import date
from pathlib import Path

import pyodbc


# Drivers tried in preference order when DB_DRIVER is not set.
_DRIVER_CANDIDATES = [
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
]


def _resolve_driver() -> str:
    """Return an installed ODBC driver name, or raise if none found."""
    explicit = os.environ.get("DB_DRIVER", "").strip()
    if explicit:
        return explicit

    installed = {d for d in pyodbc.drivers()}
    for candidate in _DRIVER_CANDIDATES:
        if candidate in installed:
            return candidate

    raise RuntimeError(
        "No supported ODBC driver found. "
        "Install 'ODBC Driver 18 for SQL Server' or '17' and try again, "
        "or set the DB_DRIVER environment variable explicitly."
    )


def _connection_string(database: str) -> str:
    driver = _resolve_driver()
    server = os.environ["DB_SERVER"]
    user = os.environ["DB_USER"]
    password = os.environ["DB_PASSWORD"]

    def quoted(value: str) -> str:
        return "{" + value.replace("}", "}}") + "}"

    trust_cert = "yes" if os.environ.get("DB_TRUST_SERVER_CERT", "false").lower() in (
        "1", "true", "yes"
    ) else "no"

    return (
        f"DRIVER={quoted(driver)};"
        f"SERVER={quoted(server)};"
        f"DATABASE={quoted(database)};"
        f"UID={quoted(user)};"
        f"PWD={quoted(password)};"
        f"TrustServerCertificate={trust_cert};"
    )


def get_connection(database: str | None = None) -> pyodbc.Connection:
    """
    Return an open pyodbc connection to the SQL Server gold database.

    Reads connection parameters from environment variables.
    Raises RuntimeError for missing or invalid configuration.
    """
    required = ("DB_SERVER", "DB_NAME", "DB_USER", "DB_PASSWORD")
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}"
        )

    return pyodbc.connect(_connection_string(database or os.environ["DB_NAME"]))

def get_watermark(
    pipeline_name: str = "daily_exchange_rate_pipeline",
) -> date | None:
    """Return the latest date successfully committed to Gold."""
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT last_successful_date
            FROM gold.pipeline_watermark
            WHERE pipeline_name = ?
            """,
            pipeline_name,
        )
        row = cursor.fetchone()
        return row[0] if row else None
    finally:
        connection.close()


def get_pending_date(
    pipeline_name: str = "daily_exchange_rate_pipeline",
) -> date | None:
    """Return the date whose load needs to be retried."""
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT pending_date
            FROM gold.pipeline_watermark
            WHERE pipeline_name = ?
            """,
            pipeline_name,
        )
        row = cursor.fetchone()
        return row[0] if row else None
    finally:
        connection.close()


def mark_pending_date(
    processing_date: str,
    pipeline_name: str = "daily_exchange_rate_pipeline",
) -> None:
    """Save the date being attempted, so a failed load can be retried."""
    target_date = date.fromisoformat(processing_date)
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            MERGE gold.pipeline_watermark WITH (HOLDLOCK) AS target
            USING (SELECT ? AS pipeline_name, ? AS pending_date) AS source
              ON target.pipeline_name = source.pipeline_name
            WHEN MATCHED THEN
              UPDATE SET pending_date = source.pending_date,
                         updated_at_utc = SYSUTCDATETIME()
            WHEN NOT MATCHED BY TARGET THEN
              INSERT (pipeline_name, pending_date)
              VALUES (source.pipeline_name, source.pending_date);
            """,
            pipeline_name,
            target_date,
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def advance_watermark(
    processing_date: str,
    pipeline_name: str = "daily_exchange_rate_pipeline",
) -> None:
    """Advance the watermark after a successful Gold load."""
    target_date = date.fromisoformat(processing_date)
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            MERGE gold.pipeline_watermark WITH (HOLDLOCK) AS target
            USING (
                SELECT ? AS pipeline_name, ? AS last_successful_date
            ) AS source
              ON target.pipeline_name = source.pipeline_name
            WHEN MATCHED THEN
              UPDATE SET
                last_successful_date = CASE
                    WHEN target.last_successful_date IS NULL
                      OR target.last_successful_date
                           < source.last_successful_date
                    THEN source.last_successful_date
                    ELSE target.last_successful_date
                END,
                pending_date = CASE
                    WHEN target.pending_date IS NULL
                      OR target.pending_date <= source.last_successful_date
                    THEN NULL
                    ELSE target.pending_date
                END,
                updated_at_utc = SYSUTCDATETIME()
            WHEN NOT MATCHED BY TARGET THEN
              INSERT (pipeline_name, last_successful_date, pending_date)
              VALUES (source.pipeline_name, source.last_successful_date, NULL);
            """,
            pipeline_name,
            target_date,
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

def _run_sql_file(cursor: pyodbc.Cursor, path: Path) -> None:
    """Execute sqlcmd-style batches separated by standalone GO lines."""
    batches = re.split(r"(?im)^\s*GO\s*(?:--.*)?$", path.read_text(encoding="utf-8-sig"))
    for batch in batches:
        if batch.strip():
            cursor.execute(batch)


def initialize_database() -> None:
    """Create the target database and apply the idempotent Gold SQL scripts."""
    database = os.environ.get("DB_NAME", "")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,127}", database):
        raise RuntimeError("DB_NAME must be a simple SQL identifier (letters, digits, underscores)")

    attempts = max(1, int(os.environ.get("DB_CONNECT_ATTEMPTS", "30")))
    delay = max(0.0, float(os.environ.get("DB_CONNECT_DELAY_SECONDS", "2")))
    connection = None
    for attempt in range(1, attempts + 1):
        try:
            connection = get_connection(database="master")
            break
        except pyodbc.Error as exc:
            if attempt == attempts:
                raise RuntimeError(
                    f"SQL Server was unavailable after {attempts} connection attempts"
                ) from exc
            time.sleep(delay)

    assert connection is not None
    try:
        connection.autocommit = True
        connection.cursor().execute(
            f"IF DB_ID(N'{database}') IS NULL CREATE DATABASE [{database}]"
        )
    finally:
        connection.close()

    connection = get_connection(database=database)
    try:
        cursor = connection.cursor()
        sql_root = Path(__file__).resolve().parents[2] / "sql" / "gold"
        for sql_file in sorted(sql_root.glob("*.sql")):
            _run_sql_file(cursor, sql_file)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
