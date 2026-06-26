from typing import cast
from .memory import save_user_profile
from .logging_config import logger

from langchain.tools import tool, ToolRuntime
from langgraph.store.sqlite import SqliteStore

@tool
def save_user_info(runtime: ToolRuntime, name: str, first_onboard: bool = False) -> str:
    """Save or update the core user profile information in the long-term store.

    Args:
        runtime: The global ToolRuntime context containing the storage layer.
        name: The preferred name/nickname of the user.
        first_onboard: Boolean flag indicating if onboarding is pending (True) or finished (False).
    """
    logger.info(f"save_user_info_called | name='{name}' | first_onboard={first_onboard}")

    if not runtime.store:
        logger.warning("save_user_info_failed | store is not initialized")
        return "ERROR: Storage layer is not available."

    store = cast(SqliteStore, runtime.store)

    # Formulate the fields to be updated dynamic and securely
    update_data = {}
    if name is not None:
        update_data["name"] = name

    if first_onboard is not None:
        update_data["first_onboard"] = first_onboard

    if not update_data:
        return "INFO: No profile updates were provided."

    # Invoke the long-term persistence layer to merge fields safely
    save_user_profile(store, **update_data)
    
    logger.info("save_user_info_success | profile updated in long-term store")
    return f"SUCCESS: User profile has been updated successfully with: {update_data}"