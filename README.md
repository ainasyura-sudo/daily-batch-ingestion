# Daily Exchange-Rate Pipeline

A daily batch pipeline that fetches USD exchange rates from a REST API,
stores source data in Bronze, cleans it into Silver, and loads a SQL Server
star schema in Gold.

## Data Source

- Endpoint: https://api.frankfurter.dev/v2/rates
- Parameters: `date=YYYY-MM-DD`, `base=USD`, `quotes=EUR,GBP,MYR`
- Response fields: `date`, `base`, `quote`, `rate`
- Pagination is not applicable to this bounded request: the selected
  currencies are retrieved in one response.

The client uses a 5-second connection timeout and a 15-second read timeout.
It makes up to four attempts with exponential backoff for connection
failures, timeouts, HTTP 429 and HTTP 500-series responses.

HTTP 429 handling uses `Retry-After` when available, with a maximum wait
of 30 seconds per retry.

Malformed JSON, empty responses, missing fields, unexpected dates or
currencies, and duplicate or missing quotes cause the batch to fail.

Rates are daily reference rates. A request fails validation if the API
does not return all requested currencies for the exact processing date.

## Layers

- **Bronze:** source JSON and ingestion metadata under
  `data/raw/YYYY/MM/DD/`, including ingestion time and source endpoint.
- **Silver:** cleaned CSV under `data/silver/YYYY/MM/DD/`.
  The business key is `(rate_date, base_currency, quote_currency)`.
  Identical duplicates collapse; conflicting duplicates and malformed
  records fail validation.
- **Gold:** SQL Server schema `gold`, containing `dim_date`,
  `dim_currency` and `fact_exchange_rate`. SQL scripts are in `sql/gold/`.

A captured Bronze response and its ingestion metadata are available in
[examples/bronze/](examples/bronze/).

## Configuration

Create the local environment file:

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

Never commit `.env`. Keep `.env.example` free of real credentials.

Compose overrides the pipeline connection to use `db,1433` and the
`sa` login. It uses `DB_PASSWORD` as the SQL Server container password.
Choose a password that meets SQL Server's password complexity policy.

If `--date` is omitted, the pipeline uses the current date in the
`Asia/Kuala_Lumpur` timezone.

## Run With Docker Compose

Prerequisite: Docker Desktop with a running Linux container engine.

After configuring `.env`, run:

```powershell
docker compose up --build
```

Compose starts SQL Server and runs the pipeline for today's date.
It sets `DB_INITIALIZE=true`, enabling database creation and execution
of the Gold schema scripts. Database connection attempts are retried
during initialization.

The pipeline exits with code 0 on success. The database container
continues running. A failed batch exits nonzero.

To run for today again:

```powershell
docker compose run --rm pipeline
```

To run for a specific date:

```powershell
docker compose run --rm pipeline --date 2026-09-21
```

After changing Python code or dependencies, rebuild when running:

```powershell
docker compose run --build --rm pipeline --date 2026-09-21
```

To inspect service status and logs from `docker compose up`:

```powershell
docker compose ps -a
docker compose logs pipeline
```

Bronze and Silver files persist in the bind-mounted `data/` folder.
SQL Server data persists in the `mssql_data` named volume.

To stop the services while preserving database data:

```powershell
docker compose down
```

The Docker SQL Server instance is separate from the company SQL Server
instance, even when both databases are named `TrainingDB`.

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

Run for today:

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

Local database initialization is disabled by default.
Set `DB_INITIALIZE=true` when automatic database initialization is intended
and the login has the required permissions.

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

The fact table references `dim_date` and uses `dim_currency` twice:
once for the base currency and once for the quote currency.

The model includes:

- Primary keys on all three tables.
- Foreign keys from the fact table to the dimensions.
- Unique date and currency-code constraints.
- A unique fact business key:
  `(date_id, base_currency_id, quote_currency_id)`.
- Indexes supporting date and quote-currency queries.

Measures include `exchange_rate` and `inverse_rate`, calculated as
`1 / exchange_rate`.

Analytics views:

- `gold.vw_fx_daily`: daily rates with calendar and currency attributes.
- `gold.vw_fx_monthly_avg`: monthly averages, minimums, maximums and
  the number of loaded rate observations per currency pair.

Monthly results reflect the dates loaded into the database.

Monthly results reflect the dates loaded into the database.

Detailed table definitions, keys and indexes are documented in
[docs/data_model.md](docs/data_model.md).

## Query Gold

Connect to the intended SQL Server instance and the database configured
by `DB_NAME`. For the demonstrated `TrainingDB` setup:

```sql
USE TrainingDB;
GO

SELECT *
FROM gold.vw_fx_daily
WHERE rate_date = '2026-09-21';

SELECT *
FROM gold.vw_fx_monthly_avg;
```

For Docker, connect to `localhost,1433` using SQL Server authentication
and the configured container credentials.

## Idempotency

Bronze and Silver files are replaced for the requested processing date.
Gold skips existing facts using the business key
`(date_id, base_currency_id, quote_currency_id)`.

Gold inserts missing facts and updates existing facts when the source
rate changes. Unchanged facts are skipped. The unique business key
prevents duplicate rows.

`loaded_at_utc` records the latest insertion or rate-update time.

The Gold load commits on success and rolls back on failure.

## Logging and Metrics

The pipeline emits JSON logs with UTC timestamps, processing dates,
and success or failure status.

Completion logs include records fetched, fact rows inserted,
layer durations and total pipeline duration.

Failure logs identify the failed stage and exception.
Successful runs exit with code 0; failed runs exit with code 1.

Unit-test evidence is available in
[docs/evidence/unit-tests.txt](docs/evidence/unit-tests.txt).

## Tests

Run the automated tests:

```powershell
python -m unittest discover -s tests -v
```

The verified test run passed all 21 tests covering:

- API success, retries, timeouts and missing fields.
- Database initialization and SQL batch execution.
- Silver cleaning and duplicate handling.
- Gold loading, skipped existing facts, rollback and date attributes.
- Inverse-rate calculation.

## Verification Evidence

For processing date `2026-09-21`:

- The first Docker run inserted 3 fact rows.
- The second Docker run inserted 0 additional fact rows.
- `docker compose up --build` completed the pipeline with exit code 0.
- SQL Server remained running after the batch completed.

Verification using the separate Compose project `fx-clean-check` and
a new database volume succeeded: database initialization completed,
3 fact rows were inserted, and the pipeline exited with code 0.

Default-date execution was verified locally and in Docker.
Without `--date`, both selected `2026-09-30` and successfully loaded
3 exchange-rate records through Bronze, Silver and Gold.

To check the stored count for the demonstrated date:

```sql
USE TrainingDB;
GO

SELECT COUNT(*) AS fact_rows
FROM gold.fact_exchange_rate
WHERE date_id = 20260921;
```

Expected count: 3 after both runs.

## Troubleshooting

- **Docker command not found:** install Docker Desktop and reopen the terminal.
- **Docker Engine unavailable:** open Docker Desktop and confirm the engine is running.
- **Missing DB variables:** check `.env`, its location and `load_dotenv()`.
- **Missing Python package:** update `requirements.txt` and rebuild the image.
- **Timezone data unavailable:** install `tzdata` and rebuild the image.
- **SQL syntax error near BOM:** read SQL files using `utf-8-sig`.
- **Database unavailable:** check the target server, credentials and initialization logs.
- **Unexpected processing date:** check whether Compose's `command` supplies `--date`.
- **No rates for the requested date:** choose a date with published rates or retry
  after publication. The client rejects incomplete or mismatched-date responses.