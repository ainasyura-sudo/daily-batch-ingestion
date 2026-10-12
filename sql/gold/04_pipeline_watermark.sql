-- Track the latest date successfully loaded into Gold.
IF OBJECT_ID(N'gold.pipeline_watermark', N'U') IS NULL
BEGIN
    CREATE TABLE gold.pipeline_watermark (
        pipeline_name        VARCHAR(100) NOT NULL,
        last_successful_date DATE         NULL,
        pending_date         DATE         NULL,
        updated_at_utc       DATETIME2(0) NOT NULL
            CONSTRAINT df_pipeline_watermark_updated_at_utc
            DEFAULT SYSUTCDATETIME(),

        CONSTRAINT pk_pipeline_watermark
            PRIMARY KEY CLUSTERED (pipeline_name)
    );
END;
GO

-- Add pending_date if the watermark table already exists without it.
IF COL_LENGTH(N'gold.pipeline_watermark', N'pending_date') IS NULL
BEGIN
    ALTER TABLE gold.pipeline_watermark
        ADD pending_date DATE NULL;
END;
GO