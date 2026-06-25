"""Automation tests for the database module (db.py) using the unittest framework."""

import os
import sys
import shutil
import sqlite3

import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.expense_agent import db


class TestDatabaseSystem(unittest.TestCase):
    """Test suite for validating database schema, constraints, and views."""

    def setUp(self) -> None:
        """Run automatically before each test. Sets up an in-memory database."""
        # Define a unique directory for testing to isolate from production data
        self.test_dir = "./tests_data_env"
        os.makedirs(self.test_dir, exist_ok=True)

        # Redirect the application's DATA_DIR to our test folder
        db.settings.DATA_DIR = self.test_dir

        # Initialize the connection (this creates the actual 'expense.db' file)
        self.conn = db.get_connection()

    def tearDown(self) -> None:
        # Explicitly close connection
        self.conn.close()

        # Delete the entire test directory and its contents
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_database_initialization(self):
        """Verify database connection object and PRAGMA configurations."""
        # Check if the connection object is valid
        self.assertIsInstance(self.conn, sqlite3.Connection)

        # Fetch active SQLite configurations
        wal_status = self.conn.execute("PRAGMA journal_mode;").fetchone()[0]
        fk_status = self.conn.execute("PRAGMA foreign_keys;").fetchone()[0]

        # Assert configurations are correct
        self.assertEqual(wal_status, "wal")
        self.assertEqual(fk_status, 1)

    def test_view_balance_calculation(self):
        """Verify real-time current balance calculation in source_balance VIEW."""
        # 1. Add sample data to test the view formula
        self.conn.executescript("""
            INSERT INTO category (category_name) 
            VALUES ('Food');
                                
            INSERT INTO source (source_name, initial_balance)
            VALUES ('Cash', 500000);
                                
            INSERT INTO transactions (date, amount, transaction_type, category_id, source_id) 
            VALUES ('2026-06-25', 200000, 'income', 1, 1);
                                
            INSERT INTO transactions (date, amount, transaction_type, category_id, source_id)
            VALUES ('2026-06-25', 50000, 'expense', 1, 1);
        """)

        # 2. Query the view (Expected balance: 500k + 200k - 50k = 650k)
        row = self.conn.execute(
            "SELECT current_balance FROM source_balance WHERE source_id = 1;"
        ).fetchone()[0]

        # Assert calculation accuracy
        self.assertEqual(row, 650000)

    def test_foreign_key_constraint(self):
        """Verify that foreign key constraints block invalid relational data."""
        # Try to insert a transaction with a non-existent source_id (999)
        # It must raise an IntegrityError due to PRAGMA foreign_keys = ON
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("""
                INSERT INTO transactions (date, amount, transaction_type, category_id, source_id)
                VALUES ('2026-06-25', 10000, 'expense', 1, 999);
            """)


if __name__ == "__main__":
    unittest.main()