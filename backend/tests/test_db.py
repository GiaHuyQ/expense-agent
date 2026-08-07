import os
import shutil
import sys
import unittest

import aiosqlite

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.expense_agent import db as db_module
from src.expense_agent.db import create_database


class TestDatabaseSystem(unittest.IsolatedAsyncioTestCase):
    """
    Full async test suite for ExpenseDB (aiosqlite-based).
    """

    async def asyncSetUp(self):
        self.test_dir = "./tests_data_env"
        os.makedirs(self.test_dir, exist_ok=True)
        db_module.settings.DATA_DIR = self.test_dir

        self.db = await create_database()
        self.conn = self.db.write_conn

    async def asyncTearDown(self):
        await self.db.write_conn.close()
        await self.db.read_conn.close()

        shutil.rmtree(self.test_dir, ignore_errors=True)

    async def test_database_initialization(self):
        """Verify WAL mode and foreign keys are enabled."""

        cursor = await self.conn.execute("PRAGMA journal_mode;")
        journal_mode = await cursor.fetchone()

        cursor = await self.conn.execute("PRAGMA foreign_keys;")
        fk = await cursor.fetchone()

        # normalize fetchone results which may be None
        journal_mode_val = journal_mode[0].lower() if journal_mode and journal_mode[0] is not None else None
        fk_val = fk[0] if fk and fk[0] is not None else None

        self.assertEqual(journal_mode_val, "wal")
        self.assertEqual(fk_val, 1)

    async def test_foreign_key_constraint(self):
        """Ensure invalid source_id is rejected."""

        await self.conn.executescript("""
            INSERT INTO categories (category_name)
            VALUES ('Food');

            INSERT INTO sources (source_name, balance)
            VALUES ('Cash', 500000);
        """)

        with self.assertRaises(aiosqlite.IntegrityError):
            await self.conn.execute("""
                INSERT INTO transactions (
                    transaction_date,
                    amount,
                    transaction_type,
                    category_id,
                    source_id
                )
                VALUES (
                    '2026-06-25',
                    10000,
                    'expense',
                    1,
                    999
                );
            """)

if __name__ == "__main__":
    unittest.main()