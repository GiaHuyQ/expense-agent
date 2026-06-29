from typing import cast, Any
from .memory import save_user_profile
from .logging_config import logger

from langchain.tools import tool, ToolRuntime
from langgraph.store.sqlite.aio import AsyncSqliteStore

@tool
async def save_user_info(runtime: ToolRuntime, name: str, first_onboard: bool = False) -> dict[str, Any]:
    """Save the user profile.

    Args:
        name: User name.
        first_onboard: Onboarding status.
    """
    logger.info(
        "save_user_info_called | name=%s | first_onboard=%s",
        name,
        first_onboard
    )

    if runtime.store is None:
        logger.warning("save_user_info_failed | store is not initialized")
        return {"status": "error"}

    store = cast(AsyncSqliteStore, runtime.store)

    # Formulate the fields to be updated dynamic and securely
    update_data = {
        "name": name,
        "first_onboard": first_onboard,
    }

    # Invoke the long-term persistence layer to merge fields safely
    await save_user_profile(store, **update_data)
    
    logger.info(
        "save_user_info_success | name=%s | first_onboard=%s",
        name,
        first_onboard,
    )

    return {
        "status": "success",
        "user_profile": update_data
    }