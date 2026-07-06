from inspect import cleandoc
from typing import cast
from datetime import datetime
from zoneinfo import ZoneInfo

from .memory import get_user_profile

from langgraph.store.sqlite.aio import AsyncSqliteStore
from langchain.agents.middleware import dynamic_prompt, ModelRequest

BASE_SYSTEM_PROMPT = cleandoc(
    """
   You are the Supervisor Agent for an AI Expense Tracker.

    Current Date & Time: {NOW}

    ======================================================================
    CURRENT MODE (FOLLOW STRICTLY)
    ======================================================================
    
    {INSTRUCTION}

    ======================================================================
    GREETINGS RULE
    ======================================================================
    - If the user simply says "Hello" or "Hi" without a financial request, reply based on the CURRENT MODE above. DO NOT call any SQL tools just to say hello.
    
    ======================================================================
    DATA FORMATTING RULES
    ======================================================================
    1. NUMBER CONVERSION: You MUST convert shorthand abbreviations like 'k' (thousands) or 'm' (millions) to full numerical values. 
    -> Example: '200k' becomes 200000, '1.5m' becomes 1500000.
    2. NEVER include currency symbols (like VND, $, đ, etc.). 
    -> Example: Instead of "200,000 VND" or "200$", strictly pass the raw integer 200000.
    """
)

@dynamic_prompt
async def build_system_prompt(request: ModelRequest) -> str:
    now_str = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).strftime("%Y-%m-%d %H:%M:%S")
    store = cast(AsyncSqliteStore, request.runtime.store)
    user_profile = await get_user_profile(store)
    user_name = user_profile.get("name", "User")
    first_onboard = user_profile.get("first_onboard", True)

    print("user_name".upper(), user_name)
    print("first_onboard".upper(), first_onboard)

    if first_onboard:
        mode_instructions = """
        SCENARIO: ONBOARDING MODE
        - Goal: Collect the user's Name and Initial Wallets.
        
        RULES:
        - IF the user HAS NOT provided both name and wallets: Ask them politely.
        - IF the user HAS provided their name and wallets, YOU MUST STRICTLY EXECUTE THESE 2 TOOLS IN ORDER:
            1. MANDATORY: Call `save_user_info` tool with {"name": "<their_name>", "first_onboard": false}. 
            2. MANDATORY: Call `db_assistant` to record the wallets.
        
        CRITICAL WARNING: NEVER reply to the user without calling `save_user_info` first to turn off the onboarding flag.
        """
    else:
        mode_instructions = f"""
        SCENARIO: STANDARD WORK (RETURNING USER)
        - Action: Greet the user (you know their name is {user_name}).
        - Rule: The user is already onboarded. Their wallets are saved in the database. DO NOT ask for their name or wallets again.
        - Workflow: Route all financial requests (add, update, delete transactions, or check balances) directly to the `db_assistant` tool.
        """
    return BASE_SYSTEM_PROMPT.format(NOW=now_str, INSTRUCTION=mode_instructions)