-- =============================================================
-- Gold Layer: Seed dim_currency
-- Idempotent: uses MERGE so safe to re-run at any time.
-- Add new currencies here as needed.
-- =============================================================

MERGE gold.dim_currency AS target
USING (
    VALUES
        ('EUR', 'Euro'),
        ('GBP', 'British Pound Sterling'),
        ('MYR', 'Malaysian Ringgit'),
        ('USD', 'US Dollar')
) AS source (currency_code, currency_name)
ON target.currency_code = source.currency_code
WHEN MATCHED AND target.currency_name <> source.currency_name THEN
    UPDATE SET currency_name = source.currency_name
WHEN NOT MATCHED BY TARGET THEN
    INSERT (currency_code, currency_name)
    VALUES (source.currency_code, source.currency_name);
GO
