-- =============================================================
-- Gold Layer: Star Schema DDL
-- Target:  SQL Server (2016+)
-- Schema:  gold
-- Run order: 01 -> 02 -> 03
-- =============================================================

-- -------------------------------------------------------
-- 0. Schema
-- -------------------------------------------------------
IF NOT EXISTS (
    SELECT 1 FROM sys.schemas WHERE name = 'gold'
)
    EXEC sp_executesql N'CREATE SCHEMA gold';
GO

-- -------------------------------------------------------
-- 1. dim_date
--    One row per calendar date that appears in the data.
-- -------------------------------------------------------
IF NOT EXISTS (
    SELECT 1 FROM sys.objects
    WHERE object_id = OBJECT_ID(N'gold.dim_date')
      AND type = 'U'
)
BEGIN
    CREATE TABLE gold.dim_date (
        date_id     INT          NOT NULL,   -- YYYYMMDD integer key
        rate_date   DATE         NOT NULL,
        [year]      SMALLINT     NOT NULL,
        quarter     TINYINT      NOT NULL,   -- 1-4
        [month]     TINYINT      NOT NULL,   -- 1-12
        month_name  VARCHAR(9)   NOT NULL,   -- 'January' ... 'December'
        [day]       TINYINT      NOT NULL,   -- 1-31
        day_of_week TINYINT      NOT NULL,   -- 1=Sunday ... 7=Saturday (DATEFIRST 7)
        day_name    VARCHAR(9)   NOT NULL,   -- 'Sunday' ... 'Saturday'
        is_weekend  BIT          NOT NULL,

        CONSTRAINT pk_dim_date PRIMARY KEY CLUSTERED (date_id),
        CONSTRAINT uq_dim_date_rate_date UNIQUE (rate_date)
    );
END;
GO

-- -------------------------------------------------------
-- 2. dim_currency
--    One row per ISO 4217 currency code.
-- -------------------------------------------------------
IF NOT EXISTS (
    SELECT 1 FROM sys.objects
    WHERE object_id = OBJECT_ID(N'gold.dim_currency')
      AND type = 'U'
)
BEGIN
    CREATE TABLE gold.dim_currency (
        currency_id   SMALLINT     NOT NULL IDENTITY(1,1),
        currency_code CHAR(3)      NOT NULL,   -- e.g. 'USD'
        currency_name VARCHAR(60)  NOT NULL,   -- e.g. 'US Dollar'

        CONSTRAINT pk_dim_currency PRIMARY KEY CLUSTERED (currency_id),
        CONSTRAINT uq_dim_currency_code UNIQUE (currency_code)
    );
END;
GO

-- -------------------------------------------------------
-- 3. fact_exchange_rate
--    One row per (date, base currency, quote currency).
-- -------------------------------------------------------
IF NOT EXISTS (
    SELECT 1 FROM sys.objects
    WHERE object_id = OBJECT_ID(N'gold.fact_exchange_rate')
      AND type = 'U'
)
BEGIN
    CREATE TABLE gold.fact_exchange_rate (
        rate_id           INT            NOT NULL IDENTITY(1,1),
        date_id           INT            NOT NULL,
        base_currency_id  SMALLINT       NOT NULL,
        quote_currency_id SMALLINT       NOT NULL,
        exchange_rate     DECIMAL(18, 6) NOT NULL,   -- base -> quote
        inverse_rate      DECIMAL(18, 6) NOT NULL,   -- quote -> base (1/rate)
        loaded_at_utc     DATETIME2(0)   NOT NULL DEFAULT SYSUTCDATETIME(),

        CONSTRAINT pk_fact_exchange_rate
            PRIMARY KEY CLUSTERED (rate_id),

        CONSTRAINT fk_fact_date
            FOREIGN KEY (date_id)
            REFERENCES gold.dim_date (date_id),

        CONSTRAINT fk_fact_base_currency
            FOREIGN KEY (base_currency_id)
            REFERENCES gold.dim_currency (currency_id),

        CONSTRAINT fk_fact_quote_currency
            FOREIGN KEY (quote_currency_id)
            REFERENCES gold.dim_currency (currency_id),

        -- Business key: one row per date x base x quote
        CONSTRAINT uq_fact_date_base_quote
            UNIQUE (date_id, base_currency_id, quote_currency_id)
    );

    -- Non-clustered index: queries filtering by date range
    CREATE NONCLUSTERED INDEX ix_fact_date_id
        ON gold.fact_exchange_rate (date_id)
        INCLUDE (base_currency_id, quote_currency_id, exchange_rate);

    -- Non-clustered index: queries pivoting on quote currency
    CREATE NONCLUSTERED INDEX ix_fact_quote_currency
        ON gold.fact_exchange_rate (quote_currency_id, date_id)
        INCLUDE (base_currency_id, exchange_rate, inverse_rate);
END;
GO
