-- =============================================================
-- Gold Layer: Analytics Views
-- =============================================================

-- -------------------------------------------------------
-- vw_fx_daily
-- Fully denormalised, human-readable daily exchange rates.
-- Typical use: dashboards, ad-hoc queries, BI tool sources.
-- -------------------------------------------------------
CREATE OR ALTER VIEW gold.vw_fx_daily AS
SELECT
    d.rate_date,
    d.[year],
    d.quarter,
    d.[month],
    d.month_name,
    d.[day],
    d.day_name,
    d.is_weekend,
    base.currency_code  AS base_currency,
    base.currency_name  AS base_currency_name,
    quote.currency_code AS quote_currency,
    quote.currency_name AS quote_currency_name,
    f.exchange_rate,
    f.inverse_rate,
    f.loaded_at_utc
FROM gold.fact_exchange_rate f
JOIN gold.dim_date     d     ON d.date_id    = f.date_id
JOIN gold.dim_currency base  ON base.currency_id  = f.base_currency_id
JOIN gold.dim_currency quote ON quote.currency_id = f.quote_currency_id;
GO

-- -------------------------------------------------------
-- vw_fx_monthly_avg
-- Average exchange rate per month, base, and quote currency.
-- Useful for trend analysis and reporting.
-- -------------------------------------------------------
CREATE OR ALTER VIEW gold.vw_fx_monthly_avg AS
SELECT
    d.[year],
    d.[month],
    d.month_name,
    base.currency_code  AS base_currency,
    quote.currency_code AS quote_currency,
    COUNT(*)                          AS trading_days,
    CAST(AVG(f.exchange_rate) AS DECIMAL(18, 6)) AS avg_exchange_rate,
    CAST(MIN(f.exchange_rate) AS DECIMAL(18, 6)) AS min_exchange_rate,
    CAST(MAX(f.exchange_rate) AS DECIMAL(18, 6)) AS max_exchange_rate,
    CAST(AVG(f.inverse_rate)  AS DECIMAL(18, 6)) AS avg_inverse_rate
FROM gold.fact_exchange_rate f
JOIN gold.dim_date     d     ON d.date_id    = f.date_id
JOIN gold.dim_currency base  ON base.currency_id  = f.base_currency_id
JOIN gold.dim_currency quote ON quote.currency_id = f.quote_currency_id
GROUP BY
    d.[year],
    d.[month],
    d.month_name,
    base.currency_code,
    quote.currency_code;
GO
