import os
import shutil
import unittest

from ..src.expense_agent.db import create_database
from ..src.expense_agent import db as db_module

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
            INSERT INTO category (category_name)
            VALUES ('Food');

            INSERT INTO source (source_name, initial_balance)
            VALUES ('Cash', 500000);
        """)

        with self.assertRaises(Exception):
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

    async def test_view_balance_calculation(self):
        """Verify source_balance view correctness."""

        await self.conn.executescript("""
            INSERT INTO category (category_name)
            VALUES ('Food');

            INSERT INTO source (source_name, initial_balance)
            VALUES ('Cash', 500000);

            INSERT INTO transactions (
                transaction_date,
                amount,
                transaction_type,
                category_id,
                source_id
            )
            VALUES ('2026-06-25', 200000, 'income', 1, 1);

            INSERT INTO transactions (
                transaction_date,
                amount,
                transaction_type,
                category_id,
                source_id
            )
            VALUES ('2026-06-25', 50000, 'expense', 1, 1);
        """)

        await self.conn.commit()

        cursor = await self.conn.execute("""
            SELECT current_balance
            FROM source_balance
            WHERE source_id = 1;
        """)

        row = await cursor.fetchone()

        row_val = row[0] if row and row[0] is not None else None

        # 500000 + 200000 - 50000 = 650000
        self.assertEqual(row_val, 650000)

if __name__ == "__main__":
    unittest.main()