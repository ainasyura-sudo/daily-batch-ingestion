# Daily Exchange-Rate Pipeline

A daily batch pipeline that fetches USD exchange rates from a REST API,
stores the source data in Bronze, cleans and validates it in Silver, and
loads an analytics-ready SQL Server star schema in Gold.

## Data Source

- **Endpoint:** [Frankfurter API](https://api.frankfurter.dev/v2/rates)
- **Parameters:** `date=YYYY-MM-DD`, `base=USD`, `quotes=EUR,GBP,MYR`
- **Response fields:** `date`, `base`, `quote`, `rate`
- The selected currencies are retrieved in one API response.

The client uses a 5-second connection timeout and a 15-second read timeout.
It makes up to four attempts, using exponential backoff for connection
failures, timeouts, HTTP 429 and HTTP 500-series responses.

For HTTP 429 responses, the client uses the `Retry-After` header when
available, with a maximum wait of 30 seconds per retry.

Malformed JSON, empty responses, missing fields, unexpected dates or
currencies, and duplicate or missing quotes cause the batch to fail.

Rates are daily reference rates, not live trading prices. A request fails
validation if the API does not return all requested currencies for the exact
processing date.

## Pipeline Layers

- **Bronze:** source JSON and ingestion metadata under
  `data/raw/YYYY/MM/DD/`. Metadata includes the ingestion time and source URL.
- **Silver:** cleaned CSV under `data/silver/YYYY/MM/DD/`. The business key is
  `(rate_date, base_currency, quote_currency)`. Identical duplicates collapse;
  conflicting duplicates and malformed records fail validation. Great
  Expectations checks the CSV schema, null values, allowed currencies,
  positive rates and unique business keys before Gold loading.
- **Gold:** SQL Server schema `gold`, containing `dim_date`, `dim_currency`
  and `fact_exchange_rate`. SQL scripts are in `sql/gold/`.

A sample Bronze response and its metadata are available in
[`examples/bronze/`](examples/bronze/).

## Configuration

Create a local environment file:

```powershell
Copy-Item .env.example .env
```

Edit `.env` and configure:

- `DB_SERVER`: SQL Server address for local Python execution.
- `DB_NAME`: target database, such as `TrainingDB`.
- `DB_USER`: SQL Server login for local Python execution.
- `DB_PASSWORD`: private password.
- `DB_DRIVER`: optional ODBC driver selection.
- `DB_TRUST_SERVER_CERT`: whether to trust the server certificate.
- `DB_INITIALIZE`: enables database initialization when set to `true`.
- `PROCESSING_DATE`: optional date used by Docker Compose, if configured there.

Never commit `.env`. Keep `.env.example` free of real credentials.

Docker Compose connects the pipeline to `db,1433` using the `sa` login.
It uses `DB_PASSWORD` as the SQL Server container password. Choose a password
that meets SQL Server's password complexity policy.

If `--date` is omitted, the pipeline uses the current date in the
`Asia/Kuala_Lumpur` timezone.

## Run With Docker Compose

Prerequisite: Docker Desktop with a running Linux container engine.

After configuring `.env`, run:

```powershell
docker compose up --build
```

Compose starts SQL Server and runs the pipeline. It sets
`DB_INITIALIZE=true`, enabling database creation and execution of the Gold
schema scripts. Database connection attempts are retried during initialization.

The pipeline exits with code 0 on success. The database container continues
running. A failed batch exits with a non-zero code.

To run the pipeline again for today's date:

```powershell
docker compose run --rm pipeline
```

To run for a specific date:

```powershell
docker compose run --rm pipeline --date 2026-09-21
```

After changing Python code or dependencies, rebuild the image:

```powershell
docker compose run --build --rm pipeline --date 2026-09-21
```

To inspect service status and logs:

```powershell
docker compose ps -a
docker compose logs pipeline
```

Bronze and Silver files persist in the bind-mounted `data/` folder. SQL Server
data persists in the `mssql_data` named volume.

To stop the services while preserving database data:

```powershell
docker compose down
```

The Docker SQL Server instance is separate from the company SQL Server
instance, even when both databases are named `TrainingDB`.

## Scheduler

Windows Task Scheduler runs `run_daily_pipeline.bat` daily at 9:00 AM.
The batch file changes to the project directory, runs the pipeline without
`--date`, and appends output to `logs/scheduler.log`.

Because `--date` is omitted, the scheduler uses the current date in the
`Asia/Kuala_Lumpur` timezone. The task was manually run successfully. The
automatic scheduled trigger is pending verification.

To check the task's last result and next run time in PowerShell:

```powershell
Get-ScheduledTaskInfo -TaskName "Daily Exchange Rate Pipeline" |
    Select-Object LastRunTime, LastTaskResult, NextRunTime
```

A `LastTaskResult` of `0` indicates that the task completed successfully.
Check the scheduler log for pipeline details:

```powershell
Get-Content .\logs\scheduler.log -Tail 20
```

## Run Locally Without Docker

Use Python 3.10 or later and install Microsoft ODBC Driver 18 for SQL Server.
Configure `.env` to point to the intended SQL Server instance.

Create and activate a virtual environment, then install dependencies:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

The dependencies include `tzdata` for timezone support on Windows.

Run for today's date:

```powershell
python -m src.main
```

Run for a specific date:

```powershell
python -m src.main --date 2026-09-21
```

For an existing database, apply the SQL scripts in this order before loading:

1. `sql/gold/01_create_schema.sql`
2. `sql/gold/02_seed_dim_currency.sql`
3. `sql/gold/03_analytics_views.sql`

Local database initialization is disabled by default. Set
`DB_INITIALIZE=true` when automatic database initialization is intended and
the login has the required permissions.

To run Bronze and Silver without loading Gold:

```powershell
python -m src.main --date 2026-09-21 --skip-gold
```

## Gold Model

| Table | Grain | Primary key |
| --- | --- | --- |
| `gold.dim_date` | One row per calendar date represented in the data | `date_id` |
| `gold.dim_currency` | One row per currency code | `currency_id` |
| `gold.fact_exchange_rate` | One row per date, base currency and quote currency | `rate_id` |

The fact table references `dim_date` and uses `dim_currency` twice: once for
the base currency and once for the quote currency.

The model includes:

- Primary keys on all three tables.
- Foreign keys from the fact table to the dimensions.
- Unique date and currency-code constraints.
- A unique fact business key:
  `(date_id, base_currency_id, quote_currency_id)`.
- Indexes supporting date and quote-currency queries.

The fact table stores `exchange_rate` and `inverse_rate`, where
`inverse_rate` is calculated as `1 / exchange_rate`.

Analytics views:

- `gold.vw_fx_daily`: daily rates with calendar and currency attributes.
- `gold.vw_fx_monthly_avg`: monthly average, minimum and maximum rates, plus
  the number of loaded rate observations for each currency pair.

Monthly results reflect the dates loaded into the database.

Detailed table definitions, keys and indexes are documented in
[`docs/data_model.md`](docs/data_model.md).

## Dashboard

`FX_Rate_Dashboard.pbix` is a Power BI dashboard for exploring the Gold-layer
exchange-rate data. It includes:

- A date slicer.
- A quote-currency slicer.
- A currency-pairs count card.
- A table of exchange rates.
- An exchange-rate trend chart.

The dashboard uses the daily analytics view, `gold.vw_fx_daily`. Open the
`.pbix` file in Power BI Desktop and refresh the data to view the latest rates
stored in SQL Server.

## Query Gold

Connect to the intended SQL Server instance and the database configured by
`DB_NAME`. For the demonstrated `TrainingDB` setup:

```sql
USE TrainingDB;
GO

SELECT *
FROM gold.vw_fx_daily
WHERE rate_date = '2026-09-21';

SELECT *
FROM gold.vw_fx_monthly_avg;
```

For Docker, connect to `localhost,1433` using SQL Server authentication and
the configured container credentials.

## Idempotency and Updates

Bronze and Silver files are replaced for the requested processing date.

Gold uses `(date_id, base_currency_id, quote_currency_id)` as its unique
business key. Missing facts are inserted, facts are updated when the source
rate changes, and unchanged facts are skipped. This prevents duplicate rows
while keeping Gold aligned with revised source rates.

`loaded_at_utc` records the latest insertion or rate-update time. The Gold
load commits on success and rolls back on failure.

## Logging and Metrics

The pipeline emits structured JSON logs with UTC timestamps, processing dates,
and success or failure status.

The logs and completion metrics include:

- API request duration and HTTP status.
- API attempts and retries.
- Number of records fetched.
- Number of fact rows inserted.
- Bronze, Silver and Gold stage durations.
- Total pipeline duration.
- Failed stage and exception details when a run fails.

Successful runs exit with code 0. Failed runs exit with code 1.

Unit-test evidence is available in
[`docs/evidence/unit-tests.txt`](docs/evidence/unit-tests.txt).

## Tests

Run the automated tests:

```powershell
python -m unittest discover -s tests -v
```

The latest verified test run passed all 23 tests, covering:

- API success, retries, timeouts and invalid responses.
- Database initialization and SQL batch execution.
- Silver cleaning, duplicate handling and Great Expectations validation.
- Rejection of unsupported quote currencies.
- Gold loading, updates, skipped unchanged facts, rollback and date attributes.
- Inverse-rate calculation.

## Verification Evidence

For processing date `2026-09-21`:

- The first Docker run inserted 3 fact rows.
- A rerun found the existing facts and inserted 0 additional rows.
- `docker compose up --build` completed the pipeline with exit code 0.
- SQL Server remained running after the batch completed.

Default-date execution was also verified locally and in Docker. Without
`--date`, the pipeline selected `2026-09-30` in the verified runs and loaded
3 exchange-rate records through Bronze, Silver and Gold.

A local run for `2026-10-05` fetched 3 records and loaded 3 fact rows.
The Great Expectations Silver validation passed for all 3 rows.

The scheduler task was manually run successfully. Its latest task result was
`0`. The automatic scheduled trigger is pending verification.

To check the stored count for the demonstrated date:

```sql
USE TrainingDB;
GO

SELECT COUNT(*) AS fact_rows
FROM gold.fact_exchange_rate
WHERE date_id = 20260921;
```

Expected count after the first run and rerun: 3.

## Troubleshooting

- **Docker command not found:** install Docker Desktop and reopen the terminal.
- **Docker Engine unavailable:** open Docker Desktop and confirm the engine is running.
- **Missing DB variables:** check `.env`, its location and `load_dotenv()`.
- **Missing Python package:** update `requirements.txt` and reinstall dependencies;
  rebuild the Docker image if running with Compose.
- **Timezone data unavailable:** install `tzdata` and rebuild the image.
- **SQL syntax error near BOM:** read SQL files using `utf-8-sig`.
- **Database unavailable:** check the target server, credentials and initialization logs.
- **Unexpected processing date:** check whether Compose's `command` supplies `--date`.
- **No rates for the requested date:** choose a date with published rates or
  retry after publication. The client rejects incomplete or mismatched-date
  responses.
- **Scheduler did not run:** check the task's `LastTaskResult`, `NextRunTime`
  and `logs/scheduler.log`.