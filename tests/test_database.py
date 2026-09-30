import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.database import _run_sql_file, initialize_database


class TestDatabaseBootstrap(unittest.TestCase):
    def test_sql_file_is_split_on_go_batches(self):
        cursor = MagicMock()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schema.sql"
            path.write_text("SELECT 1;\nGO\n\nSELECT 2;\nGO\n", encoding="utf-8")

            _run_sql_file(cursor, path)

        self.assertEqual(cursor.execute.call_count, 2)

    def test_initialize_creates_database_and_applies_scripts(self):
        master_connection = MagicMock()
        database_connection = MagicMock()
        environment = {
            "DB_NAME": "fx_pipeline",
            "DB_CONNECT_ATTEMPTS": "1",
            "DB_CONNECT_DELAY_SECONDS": "0",
        }

        with patch.dict(os.environ, environment, clear=False), patch(
            "src.database.get_connection",
            side_effect=[master_connection, database_connection],
        ) as get_connection:
            initialize_database()

        self.assertEqual(get_connection.call_args_list[0].kwargs, {"database": "master"})
        self.assertEqual(
            get_connection.call_args_list[1].kwargs,
            {"database": "fx_pipeline"},
        )
        master_connection.cursor.return_value.execute.assert_called_once()
        database_connection.commit.assert_called_once()
        master_connection.close.assert_called_once()
        database_connection.close.assert_called_once()

    def test_database_name_is_validated_before_connecting(self):
        with patch.dict(os.environ, {"DB_NAME": "fx-pipeline"}, clear=False), patch(
            "src.database.get_connection"
        ) as get_connection:
            with self.assertRaisesRegex(RuntimeError, "DB_NAME"):
                initialize_database()

        get_connection.assert_not_called()


if __name__ == "__main__":
    unittest.main()