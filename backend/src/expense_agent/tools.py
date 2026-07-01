from typing import Any, Annotated
from .memory import save_user_profile
from .logging_config import logger

from langchain.tools import tool
from langgraph.store.base import BaseStore
from langgraph.prebuilt import InjectedStore

@tool
async def save_user_info(
    store: Annotated[BaseStore, InjectedStore()],
    name: str, 
    first_onboard: bool = False,
) -> dict[str, Any]:
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

    if not store:
        logger.warning("save_user_info_failed | store is not initialized")
        return {"status": "error"}

    update_data = {
        "name": name,
        "first_onboard": first_onboard,
    }

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