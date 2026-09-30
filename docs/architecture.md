# Pipeline Architecture

## Data Flow

1. The ingestion service requests USD exchange rates for EUR, GBP and MYR.
2. Bronze stores source JSON and ingestion metadata.
3. Silver validates, standardizes and deduplicates the data.
4. Gold loads dimensions and exchange-rate facts into SQL Server.
5. SQL views expose daily rates and monthly summaries.

## Components

| Component | Location | Responsibility |
| --- | --- | --- |
| API client | `src/api/client.py` | Requests, timeouts, retries and response validation |
| Ingestion | `src/ingestion/ingest.py` | Coordinates fetching and Bronze storage |
| Bronze | `src/storage/bronze.py` | Stores source JSON and metadata |
| Silver | `src/transformation/silver.py` | Produces cleaned CSV |
| Gold | `src/transformation/gold.py` | Loads dimensions and facts |
| Database | `src/database/__init__.py` | Connections and database initialization |
| SQL model | `sql/gold/` | Tables, constraints, indexes, seeds and views |
| Entry point | `src/main.py` | Processing date and pipeline execution |

## Gold Star Schema

The fact table grain is one row per date, base currency and quote currency.

- `gold.dim_date`: calendar attributes, keyed by `date_id`.
- `gold.dim_currency`: currency codes and names, keyed by `currency_id`.
- `gold.fact_exchange_rate`: exchange rate and inverse rate, keyed by `rate_id`.

The fact table references `dim_date` once and `dim_currency` twice:
for base and quote currencies.

A unique constraint on `(date_id, base_currency_id, quote_currency_id)`
prevents duplicate facts.

## Docker Execution

Compose runs a Python pipeline container and a SQL Server container.
The pipeline connects to `db,1433`.

Bronze and Silver persist through the `data/` bind mount.
SQL Server persists through the `mssql_data` named volume.

Docker initialization creates the target database if needed and applies
the Gold SQL scripts before loading.

## Date and Failure Handling

The pipeline accepts `--date YYYY-MM-DD`. Without it, the processing date
defaults to today in the `Asia/Kuala_Lumpur` timezone.

Transient API failures are retried with exponential backoff.
Invalid responses fail ingestion. Gold loading rolls back on failure.

## Rerun Behaviour

Bronze and Silver files are replaced for the processing date.
Gold skips existing facts and retains the first loaded rate.