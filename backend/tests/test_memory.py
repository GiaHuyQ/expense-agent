import os
import shutil
import sys
import unittest

# Cho phép import từ thư mục project
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.store.sqlite.aio import AsyncSqliteStore

from src.expense_agent import memory
from src.expense_agent.memory import (
    create_checkpointer,
    create_store,
    get_user_profile,
    save_user_profile,
)


class TestAgentMemory(unittest.IsolatedAsyncioTestCase):
    """Tests for LangGraph checkpoint and store."""

    async def asyncSetUp(self):
        self.test_dir = "./test_memory"
        os.makedirs(self.test_dir, exist_ok=True)

        memory.settings.DATA_DIR = self.test_dir

        self.checkpointer = await create_checkpointer()
        self.store = await create_store()

    async def asyncTearDown(self):
        await self.checkpointer.manager.__aexit__(None, None, None)
        await self.store.manager.__aexit__(None, None, None)

        shutil.rmtree(self.test_dir, ignore_errors=True)

    async def test_checkpointer_created(self):
        """Verify AsyncSqliteSaver is created correctly."""

        self.assertIsInstance(
            self.checkpointer.checkpointer,
            AsyncSqliteSaver,
        )

        self.assertTrue(
            os.path.exists(
                os.path.join(self.test_dir, "checkpoints.db")
            )
        )

    async def test_store_created(self):
        """Verify AsyncSqliteStore is created correctly."""

        self.assertIsInstance(
            self.store.store,
            AsyncSqliteStore,
        )

        self.assertTrue(
            os.path.exists(
                os.path.join(self.test_dir, "store.db")
            )
        )

    async def test_user_profile_lifecycle(self):
        """Verify saving and updating user profile."""

        # Empty profile
        profile = await get_user_profile(self.store.store)
        self.assertEqual(profile, {})

        # First save
        await save_user_profile(
            self.store.store,
            name="Huy",
            first_onboard=True,
        )

        profile = await get_user_profile(self.store.store)

        self.assertEqual(
            profile,
            {
                "name": "Huy",
                "first_onboard": True,
            },
        )

        # Merge update
        await save_user_profile(
            self.store.store,
            age=28,
            first_onboard=False,
        )

        profile = await get_user_profile(self.store.store)

        self.assertEqual(
            profile,
            {
                "name": "Huy",
                "first_onboard": False,
                "age": 28,
            },
        )


if __name__ == "__main__":
    unittest.main()