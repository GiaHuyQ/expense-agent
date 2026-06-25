"""Management of the agent's two persistence layers:

- Checkpointer (Short-term memory): Conversation history per thread_id.
- Store (Long-term memory): User profile (name, onboard status) across sessions.
"""

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.sqlite import SqliteStore

from .config import settings

# Global constants for user profile location in the store
USER_PROFILE_NAMESPACE = ("user_profile",)
USER_PROFILE_KEY = "default_user"

# Singleton instances to keep database connections open tracking
_checkpointer_conn = None
_checkpointer_instance: SqliteSaver | None = None

_store_conn = None
_store_instance: SqliteStore | None = None


def get_checkpointer() -> SqliteSaver:
    """Initialize or return the existing short-term memory checkpointer."""
    global _checkpointer_conn, _checkpointer_instance

    if _checkpointer_instance is None:
        # Open connection and manually enter context to keep it alive
        _checkpointer_conn = SqliteSaver.from_conn_string(
            f"{settings.DATA_DIR}/checkpoints.db"
        )
        _checkpointer_instance = _checkpointer_conn.__enter__()

    return _checkpointer_instance


def get_store() -> SqliteStore:
    """Initialize or return the existing long-term memory store."""
    global _store_conn, _store_instance

    if _store_instance is None:
        # Open connection and manually enter context to keep it alive
        _store_conn = SqliteStore.from_conn_string(
            f"{settings.DATA_DIR}/store.db"
        )
        _store_instance = _store_conn.__enter__()
        # Setup internal database tables required by LangGraph
        _store_instance.setup()

    return _store_instance


def get_user_profile(store: SqliteStore) -> dict:
    """Fetch the current user profile. Returns an empty dict if not found."""
    item = store.get(USER_PROFILE_NAMESPACE, USER_PROFILE_KEY)

    if item is not None and isinstance(item.value, dict):
        return item.value

    return {}


def save_user_profile(store: SqliteStore, **fields) -> None:
    """Merge and update the user profile with new fields."""
    # Get current profile data
    profile = get_user_profile(store)

    # Merge new fields into the existing profile
    profile.update(fields)

    # Save the updated profile back to the long-term store
    store.put(USER_PROFILE_NAMESPACE, USER_PROFILE_KEY, profile)