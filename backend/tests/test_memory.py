"""Automation tests for the agent's memory persistence layers using real physical files."""

import os
import shutil
import sys
import unittest

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.sqlite import SqliteStore

# Dynamic path configuration to allow importing from the 'src' directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.expense_agent import memory


class TestAgentMemory(unittest.TestCase):
    """Test suite for short-term (Checkpointer) and long-term (Store) memory layers."""

    def setUp(self) -> None:
        """Run automatically before each test. Creates an isolated test directory."""
        self.test_dir = "./test_memory"
        os.makedirs(self.test_dir, exist_ok=True)

        # Redirect the application's data path to our test directory
        memory.settings.DATA_DIR = self.test_dir

    def tearDown(self) -> None:
        """Run automatically after each test. Closes connections and wipes test files."""
        # 1. Safely exit Context Managers to release SQLite file locks on disk
        if memory._checkpointer_conn is not None:
            memory._checkpointer_conn.__exit__(None, None, None)
        if memory._store_conn is not None:
            memory._store_conn.__exit__(None, None, None)

        # 2. Reset global Singleton instances to ensure strict isolation between tests
        memory._checkpointer_conn = None
        memory._checkpointer_instance = None
        memory._store_conn = None
        memory._store_instance = None

        # 3. Permanently delete the temporary test folder and all active WAL files
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_checkpoint_singleton_and_file_creation(self):
        """Verify that get_checkpointer creates a physical file and acts as a Singleton."""
        checkpointer1 = memory.get_checkpointer()
        checkpointer2 = memory.get_checkpointer()

        # Check if the returned object is valid and the database file exists
        self.assertIsInstance(checkpointer1, SqliteSaver)
        self.assertTrue(os.path.exists(f"{self.test_dir}/checkpoints.db"))

        # Assert that both variables point to the exact same memory address
        self.assertIs(checkpointer1, checkpointer2)

    def test_store_singleton_and_file_creation(self):
        """Verify that get_store creates a physical file and acts as a Singleton."""
        store1 = memory.get_store()
        store2 = memory.get_store()

        # Check if the returned object is valid and the database file exists
        self.assertIsInstance(store1, SqliteStore)
        self.assertTrue(os.path.exists(f"{self.test_dir}/store.db"))

        # Assert that both variables point to the exact same memory address
        self.assertIs(store1, store2)

    def test_user_profile_lifecycle(self):
        """Test reading, initial saving, and multi-field merging within the Long-term Store."""
        store = memory.get_store()

        # 1. Initial State: Should return an empty dict if no profile exists yet
        initial_profile = memory.get_user_profile(store)
        self.assertEqual(initial_profile, {})

        # 2. First Save: Insert base fields into the user profile
        memory.save_user_profile(store, name="User_123", first_onboard=True)
        profile_after_save = memory.get_user_profile(store)
        self.assertEqual(profile_after_save, {"name": "User_123", "first_onboard": True})

        # 3. Merge/Update: Add new fields and update existing ones without data loss
        memory.save_user_profile(store, age=29, first_onboard=False)
        final_profile = memory.get_user_profile(store)

        # Verify that 'name' is preserved, 'first_onboard' is updated, and 'age' is appended
        expected_profile = {"name": "User_123", "first_onboard": False, "age": 29}
        self.assertEqual(final_profile, expected_profile)

if __name__ == "__main__":
    unittest.main()