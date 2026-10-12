import logging
from pathlib import Path

import great_expectations as gx
import pandas as pd


logger = logging.getLogger(__name__)

EXPECTED_COLUMNS = [
    "rate_date",
    "base_currency",
    "quote_currency",
    "exchange_rate",
]


def validate_silver_csv(silver_path: Path) -> None:
    """Validate the Silver CSV with Great Expectations."""
    dataframe = pd.read_csv(silver_path)

    context = gx.get_context(mode="ephemeral")
    data_source = context.data_sources.add_pandas(name="fx_silver_source")
    data_asset = data_source.add_dataframe_asset(name="exchange_rates")
    batch_definition = data_asset.add_batch_definition_whole_dataframe(
        "silver_rows"
    )
    batch = batch_definition.get_batch(
        batch_parameters={"dataframe": dataframe}
    )

    suite = gx.ExpectationSuite(name="fx_silver_quality")

    suite.add_expectation(
        gx.expectations.ExpectTableColumnsToMatchSet(
            column_set=EXPECTED_COLUMNS,
            exact_match=True,
        )
    )

    for column in EXPECTED_COLUMNS:
        suite.add_expectation(
            gx.expectations.ExpectColumnValuesToNotBeNull(column=column)
        )

    suite.add_expectation(
        gx.expectations.ExpectColumnValuesToBeInSet(
            column="base_currency",
            value_set=["USD"],
        )
    )
    suite.add_expectation(
        gx.expectations.ExpectColumnValuesToBeInSet(
            column="quote_currency",
            value_set=["EUR", "GBP", "MYR"],
        )
    )
    suite.add_expectation(
        gx.expectations.ExpectColumnValuesToBeBetween(
            column="exchange_rate",
            min_value=0,
            strict_min=True,
        )
    )
    suite.add_expectation(
        gx.expectations.ExpectCompoundColumnsToBeUnique(
            column_list=[
                "rate_date",
                "base_currency",
                "quote_currency",
            ]
        )
    )

    result = batch.validate(suite)

    if not result["success"]:
        failures = [
            item["expectation_config"]["type"]
            for item in result["results"]
            if not item["success"]
        ]
        raise ValueError(
            f"Silver data-quality checks failed: {', '.join(failures)}"
        )

    logger.info(
        "Great Expectations Silver checks passed: %d row(s)",
        len(dataframe),
    )