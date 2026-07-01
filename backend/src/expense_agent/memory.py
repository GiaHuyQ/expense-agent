from dataclasses import dataclass
from contextlib import AbstractAsyncContextManager

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.store.sqlite.aio import AsyncSqliteStore
from langgraph.store.base import BaseStore

from .config import settings

# Global constants for user profile location in the store
USER_PROFILE_NAMESPACE = ("user_profile",)
USER_PROFILE_KEY = "default_user"

@dataclass(slots=True)
class CheckpointerResource:
    manager: AbstractAsyncContextManager[AsyncSqliteSaver]
    checkpointer: AsyncSqliteSaver

async def create_checkpointer() -> CheckpointerResource:
    """Initialize or return the existing short-term memory checkpointer."""
    # Open connection and manually enter context to keep it alive
    manager = AsyncSqliteSaver.from_conn_string(
        f"{settings.DATA_DIR}/checkpoints.db"
    )

    checkpointer = await manager.__aenter__()

    return CheckpointerResource(
        manager=manager,
        checkpointer=checkpointer,
    )

@dataclass(slots=True)
class StoreResource:
    manager: AbstractAsyncContextManager[AsyncSqliteStore]
    store: AsyncSqliteStore

async def create_store() -> StoreResource:
    """Initialize or return the existing long-term memory store."""
    # Open connection and manually enter context to keep it alive
    manager = AsyncSqliteStore.from_conn_string(
        f"{settings.DATA_DIR}/store.db"
    )

    store = await manager.__aenter__()

    # Setup internal database tables required by LangGraph
    await store.setup()

    return StoreResource(
        manager=manager,
        store=store
    )


async def get_user_profile(store: BaseStore) -> dict[str, object]:
    """Fetch the current user profile. Returns an empty dict if not found."""
    item = await store.aget(USER_PROFILE_NAMESPACE, USER_PROFILE_KEY)

    if item is not None and isinstance(item.value, dict):
        return item.value

    return {}


async def save_user_profile(store: BaseStore, **fields) -> None:
    """Merge and update the user profile with new fields."""
    # Get current profile data
    profile = await get_user_profile(store)

    # Merge new fields into the existing profile
    profile.update(fields)

    # Save the updated profile back to the long-term store
    await store.aput(USER_PROFILE_NAMESPACE, USER_PROFILE_KEY, profile)