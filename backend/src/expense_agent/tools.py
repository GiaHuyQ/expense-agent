from typing import cast
from .memory import get_user_profile
from .logging import logger, setup_logging

from langchain.tools import tool, ToolRuntime
from langgraph.store.sqlite import SqliteStore

setup_logging()

@tool()
def get_user_info(runtime: ToolRuntime) -> str:
    """ 
        Get user info: name, first_onboard and all information
    """
    if not runtime.store:
        logger.warning("get_user_info_called | store is not initialized")
        return "Not any user info"

    store = cast(SqliteStore, runtime.store)

    profile = get_user_profile(store)

    logger.info(f"get_user_info_called | profile={profile}")

    if not profile:
        return "Not any user info"
    
    first_onboard = profile.get("first_onboard", False)

    return f"first_onboard={first_onboard}."
