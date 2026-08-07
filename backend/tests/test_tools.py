import os
import shutil
import sys
import unittest

from langchain_core.runnables import RunnableConfig

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.expense_agent import db as db_module
from src.expense_agent.db import create_database
from src.expense_agent.sql_agent.tools import (
    add_category,
    add_money_source,
    add_transaction,
    delete_transaction,
    transfer_money,
    update_transaction,
)


class TestAgentSQLTool(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.test_dir = "./tests_data_env"
        os.makedirs(self.test_dir, exist_ok=True)
        db_module.settings.DATA_DIR = self.test_dir

        self.db = await create_database()
        self.conn = self.db.write_conn
        self.config : RunnableConfig = {
            "configurable": {
                "db": self.db 
            }
        }

        self.addAsyncCleanup(self.db.read_conn.close)
        self.addAsyncCleanup(self.db.write_conn.close)
        self.addCleanup(shutil.rmtree, self.test_dir, ignore_errors=True)

    async def test_add_money_source_success(self) -> None:
        """Test successful creation of multiple valid money sources."""
        payload = [
            ("momo", 200000),
            ("cash", 120000),
            ("vpbank", 3000000)
        ]

        # 1. Invoke tool
        response = await add_money_source.ainvoke(
            {"sources": payload},
            config=self.config
        )

        # 2. Validate response
        self.assertEqual(response["status"], "success")
        
        results = response.get("results", [])
        self.assertEqual(len(results), len(payload))
        
        for i, (source_name, _) in enumerate(payload):
            self.assertEqual(results[i]["source_name"], source_name)
            self.assertEqual(results[i]["status"], "success")

        # 3. Validate database
        cursor = await self.conn.execute('SELECT source_name, balance FROM sources;')
        rows = await cursor.fetchall()
        db_sources = {row["source_name"]: row["balance"] for row in [dict(r) for r in rows]}

        self.assertEqual(len(payload), len(db_sources))
        for source_name, balance in payload:
            self.assertIn(source_name, db_sources)
            self.assertEqual(balance, db_sources[source_name])

    async def test_add_money_source_failed(self) -> None:
        """Test failure handling when creating a money source with a negative balance."""
        payload = [
            ("paypal", -50000)
        ]

        # 1. Invoke tool
        response = await add_money_source.ainvoke(
            {"sources": payload},
            config=self.config
        )

        # 2. Validate response
        self.assertEqual(response["status"], "success")  # Tool completed without crashing
        
        results = response.get("results", [])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["source_name"], "paypal")
        self.assertEqual(results[0]["status"], "error")
        self.assertIn("balance", results[0]["message"].lower())

        # 3. Validate database
        cursor = await self.conn.execute(
            'SELECT * FROM sources WHERE source_name = ?;', 
            ("paypal",)
        )
        row = await cursor.fetchone()
        
        # Ensure invalid record was not inserted
        self.assertIsNone(row)

    async def test_add_category_success(self) -> None:
        payload = [
            "Cafe",
            "Gasoline",
            "Shopping"
        ]

        # 1. Invoke tool
        response = await add_category.ainvoke(
            {"category_names": payload},
            config=self.config
        )

        # 2. Validate response
        self.assertEqual(response["status"], "success")

        results = response["results"]
        self.assertEqual(len(results), len(payload))

        for r in results:
            self.assertIn(r["category_name"], payload)
            self.assertEqual(r["status"], "success")

        # 3. Validate database
        cursor = await self.conn.execute('SELECT category_name FROM categories;')

        rows = await cursor.fetchall()
        db_sources = [r for r in [dict(r) for r in rows]]

        self.assertEqual(len(db_sources), len(payload) + 1) # 'Transfer' is always exists

        for r in db_sources:
            self.assertIn(r["category_name"], payload + ["Transfer"])

    async def test_add_transaction_success(self) -> None:
        sources_payload = [("cash", 200000), ("momo", 1000000)]
        categories_payload = ["cafe", "shopping"]

        await add_money_source.ainvoke({"sources": sources_payload}, self.config)
        await add_category.ainvoke({"category_names": categories_payload}, self.config)

        payload = {
            "transaction_date": "2026-07-24",
            "amount": 200000,
            "transaction_type": "expense",
            "category_id": 2,
            "source_id": 1,
            "note": "cafe with friend"
        }

        # 1. Tool invoke
        response = await add_transaction.ainvoke(payload, self.config)

        # 2. Validate response
        self.assertEqual(response["status"], "success")
        self.assertIn("transaction_id", response)
        transaction_id = response["transaction_id"]

        # 3. Validate database

        # Add transaction
        cursor = await self.conn.execute('SELECT * FROM transactions WHERE id = ?', (transaction_id,))
        row = await cursor.fetchone()

        assert row is not None

        db_transaction = dict(row)

        self.assertEqual(db_transaction["transaction_date"], payload["transaction_date"])
        self.assertEqual(db_transaction["amount"], payload["amount"])
        self.assertEqual(db_transaction["transaction_type"], payload["transaction_type"])
        self.assertEqual(db_transaction["category_id"], payload["category_id"])
        self.assertEqual(db_transaction["source_id"], payload["source_id"])
        self.assertEqual(db_transaction["note"], payload["note"])

        # Update source balance
        cursor_source = await self.conn.execute(
            'SELECT balance FROM sources WHERE source_id = ?', 
            (payload["source_id"],)
        )
        row_source = await cursor_source.fetchone()

        assert row_source is not None
        
        updated_balance = row_source["balance"]
        self.assertEqual(updated_balance, 0)

    async def test_add_transaction_failed(self) -> None:
        sources_payload = [("cash", 200000), ("momo", 1000000)]
        categories_payload = ["cafe", "shopping"]

        await add_money_source.ainvoke({"sources": sources_payload}, self.config)
        await add_category.ainvoke({"category_names": categories_payload}, self.config)

        payload = {
            "transaction_date": "2026-07-24",
            "amount": 400000,
            "transaction_type": "expense",
            "category_id": 2,
            "source_id": 1,
            "note": "cafe with friend"
        }

        # 1. Tool invoke
        response = await add_transaction.ainvoke(payload, self.config)

        # 2. Validate Response
        self.assertEqual(response["status"], "error")
        self.assertEqual(response["message"], "Insufficient balance")

        # 3. Validate Database

        # Add transaction
        cursor = await self.conn.execute("SELECT * FROM transactions;")
        row = await cursor.fetchone()

        self.assertIsNone(row)

        # Update source balance
        cursor = await self.conn.execute(
            "SELECT balance FROM sources WHERE source_id=?",
            (1,)
        )

        row = await cursor.fetchone()

        assert row is not None

        self.assertEqual(row[0], sources_payload[0][1])

    async def test_delete_transaction_success(self):
        sources_payload = [("cash", 200000), ("momo", 1000000)]
        categories_payload = ["cafe", "shopping"]

        await add_money_source.ainvoke({"sources": sources_payload}, self.config)
        await add_category.ainvoke({"category_names": categories_payload}, self.config)

        transaction_payload = {
            "transaction_date": "2026-07-24",
            "amount": 200000,
            "transaction_type": "expense",
            "category_id": 2,
            "source_id": 1,
            "note": "cafe with friend"
        }

        response = await add_transaction.ainvoke(transaction_payload, config=self.config)

        transaction_id = response["transaction_id"]

        # 1. Tool Invoke
        response = await delete_transaction.ainvoke(
            {"transaction_id": transaction_id}, 
            config=self.config
        )

        # 2. Validate Response
        self.assertEqual(response["status"], "success")
        self.assertEqual(response["transaction_id"], transaction_id)

        # 3. Validate Database

        # Delete transaction
        cursor = await self.conn.execute(
            "SELECT * FROM transactions WHERE id=?",
            (transaction_id,)
        )

        row = await cursor.fetchone()

        self.assertIsNone(row)

        # Update transaction
        cursor = await self.conn.execute(
            "SELECT balance FROM sources WHERE source_id=?",
            (transaction_payload["source_id"],)
        )

        row = await cursor.fetchone()

        assert row is not None

        self.assertEqual(row[0], sources_payload[0][1])

    async def test_transfer_money_success(self):
        sources_payload = [("cash", 200000), ("momo", 1000000)]
        response = await add_money_source.ainvoke({"sources": sources_payload}, self.config)

        cursor = await self.conn.execute(
            "SELECT source_id FROM sources WHERE source_name=?",
            (sources_payload[0][0],)
        )

        row = await cursor.fetchone()
        assert row is not None
        cash_id = row[0]

        cursor = await self.conn.execute(
            "SELECT source_id FROM sources WHERE source_name=?",
            (sources_payload[1][0],)
        )

        row = await cursor.fetchone()
        assert row is not None
        momo_id = row[0]

        payload = {
            "fromSource_id": cash_id,
            "toSource_id": momo_id,
            "amount": 50000,
            "transfer_date": "2026-07-21"
        }

        # 1. Tool Invoke
        response = await transfer_money.ainvoke(
            {
                "fromSource_id": payload["fromSource_id"],
                "toSource_id": payload["toSource_id"],
                "amount": payload["amount"],
                "transfer_date": payload["transfer_date"]
            },
            config=self.config
        )

        # 2. Validate Response

        self.assertEqual(response["status"], "success")
        self.assertEqual(response["message"], f"Successfully transferred {payload["amount"]} from {sources_payload[0][0]} to {sources_payload[1][0]}")
    
        # 3. Validate Database
        cursor = await self.conn.execute(
            "SELECT balance FROM sources WHERE source_id=?",
            (cash_id,)
        )

        row = await cursor.fetchone()

        assert row is not None

        self.assertEqual(row[0], sources_payload[0][1] - 50000)

        cursor = await self.conn.execute(
            "SELECT balance FROM sources WHERE source_id=?",
            (momo_id,)
        )

        row = await cursor.fetchone()

        assert row is not None

        self.assertEqual(row[0], sources_payload[1][1] + 50000)

    async def test_transfer_money_failed(self):
        sources_payload = [("cash", 200000), ("momo", 1000000)]
        response = await add_money_source.ainvoke({"sources": sources_payload}, self.config)

        cursor = await self.conn.execute(
            "SELECT source_id FROM sources WHERE source_name=?",
            (sources_payload[0][0],)
        )

        row = await cursor.fetchone()
        assert row is not None
        cash_id = row[0]

        cursor = await self.conn.execute(
            "SELECT source_id FROM sources WHERE source_name=?",
            (sources_payload[1][0],)
        )

        row = await cursor.fetchone()
        assert row is not None
        momo_id = row[0]

        payload = {
            "fromSource_id": cash_id,
            "toSource_id": momo_id,
            "amount": -50000,
            "transfer_date": "2026-07-21"
        }

        # 1. Tool Invoke

        response = await transfer_money.ainvoke(
            {
                "fromSource_id": payload["fromSource_id"],
                "toSource_id": payload["toSource_id"],
                "amount": payload["amount"],
                "transfer_date": payload["transfer_date"]
            },
            config=self.config
        )

        # 2. Validate Response

        self.assertEqual(response["status"], "error")
        self.assertEqual(response["message"], "Invalid amount")

        # 3. Validate Database

        cursor = await self.conn.execute(
            "SELECT balance FROM sources WHERE source_id=?",
            (cash_id,)
        )

        row = await cursor.fetchone()

        assert row is not None

        self.assertEqual(row[0], sources_payload[0][1])

        cursor = await self.conn.execute(
            "SELECT balance FROM sources WHERE source_id=?",
            (momo_id,)
        )

        row = await cursor.fetchone()

        assert row is not None

        self.assertEqual(row[0], sources_payload[1][1])

    async def test_update_transation_success(self):
        sources_payload = [("cash", 200000), ("momo", 1000000)]
        categories_payload = ["cafe", "shopping"]

        await add_money_source.ainvoke({"sources": sources_payload}, self.config)
        await add_category.ainvoke({"category_names": categories_payload}, self.config)

        transaction_payload = {
            "transaction_date": "2026-07-24",
            "amount": 200000,
            "transaction_type": "expense",
            "category_id": 2,
            "source_id": 1,
            "note": "cafe with friend"
        }

        response = await add_transaction.ainvoke(transaction_payload, config=self.config)

        transaction_id = response["transaction_id"]
 
        transaction_update_payload = {
            "transaction_id": transaction_id,
            "amount": 50000
        }

        # 1. Tool Invoke
        response = await update_transaction.ainvoke(
            transaction_update_payload,
            self.config
        )

        # 2. Validate Response
        self.assertEqual(response["status"], "success")
        self.assertEqual(response["message"], f"Successfully updated transaction_id: {transaction_id}")

        # 3. Validate Database
        # Update transaction
        cursor = await self.conn.execute(
            "SELECT amount FROM transactions WHERE id=?",
            (transaction_id,)
        )

        row = await cursor.fetchone()

        assert row is not None

        self.assertEqual(row[0], transaction_update_payload["amount"])

        # Update source balance
        cursor =  await self.conn.execute(
            "SELECT balance FROM sources WHERE source_id=?",
            (transaction_payload["source_id"],)
        )

        row = await cursor.fetchone()

        assert row is not None

        self.assertEqual(row[0], sources_payload[0][1] - transaction_update_payload["amount"])

    async def test_update_transaction_failed(self):
        sources_payload = [("cash", 200000), ("momo", 1000000)]
        categories_payload = ["cafe", "shopping"]

        await add_money_source.ainvoke({"sources": sources_payload}, self.config)
        await add_category.ainvoke({"category_names": categories_payload}, self.config)

        transaction_payload = {
            "transaction_date": "2026-07-24",
            "amount": 200000,
            "transaction_type": "expense",
            "category_id": 2,
            "source_id": 1,
            "note": "cafe with friend"
        }

        response = await add_transaction.ainvoke(transaction_payload, config=self.config)

        transaction_id = response["transaction_id"]

        transaction_update_payload = {
            "transaction_id": transaction_id,
            "source_id": 3
         }

        # 1. Tool Invoke
        response = await update_transaction.ainvoke(
            transaction_update_payload,
            self.config
        )

        # 2. Validate Response
        self.assertEqual(response["status"], "error")
        self.assertEqual(response["message"], f"source_id: {transaction_update_payload["source_id"]} not found")

        # 3. Validate Database
        cursor = await self.conn.execute(
            "SELECT source_id FROM transactions WHERE id=?",
            (transaction_id,)
        )
        row = await cursor.fetchone()

        assert row is not None

        self.assertEqual(row[0], transaction_payload["source_id"])

if __name__ == "__main__":
    unittest.main()