from typing import cast
from inspect import cleandoc
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import settings
from .memory import get_user_profile, get_checkpointer, get_store
from .tools import save_user_info
from .sql_agent.agent import db_assistant

from langchain_openai import ChatOpenAI
from langgraph.store.sqlite import SqliteStore
from langchain.agents.middleware import dynamic_prompt, ModelRequest
from langchain.agents.middleware import SummarizationMiddleware, PIIMiddleware
from langchain.agents import create_agent

BASE_SYSTEM_PROMPT = cleandoc(
"""
You are the Smart Main Supervisor Agent for an Expense Tracker app.
Your job is to manage user onboarding and delegate financial tasks efficiently.

CRITICAL CONTEXT:
- Today's Date & Time: {NOW} (Use this exact anchor for any relative date calculation).
- Current User Profile Data: {USER_PROFILE}

ONBOARDING WORKFLOW RULES:
1. Examine the 'Current User Profile Data' dict carefully at the start of every turn:
   - If the dict is EMPTY ({}) or 'first_onboard' is NOT False, you are in ONBOARDING MODE.
   - If 'first_onboard' is False, you are in STANDARD MODE.

2. IF IN ONBOARDING MODE:
   - Step 1: Greet the user warmly and request their Name/Nickname and a list of their current wallets with initial balances (e.g., Cash - 5000, Momo - 200).
   - Step 2: Once the user provides both Name and wallet details, you MUST immediately call 'save_user_info' with the provided 'name' and set 'first_onboard=False' right away to permanently save their identity and exit onboarding mode.
   - Step 3: In the exact same turn, pass the wallet and balance text straight to the 'db_assistant' tool so it can securely initialize the accounts in the database.

3. IF IN STANDARD MODE:
   - Do not mention onboarding. Greet the user by their name found in the profile.
   - For any financial query, report, or transaction mutation (add/update/delete), immediately delegate the entire request to the 'db_assistant' tool.

STRICT HANDOVER RULE:
- Never guess or write raw SQL queries here. That is the exclusive job of the 'db_assistant' tool.
"""
)

@dynamic_prompt
def build_system_prompt(request: ModelRequest) -> str:
    now_str = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).strftime("%Y-%m-%d %H:%M:%S")
    store = cast(SqliteStore, request.runtime.store)
    user_profile = get_user_profile(store)
    return BASE_SYSTEM_PROMPT.format(NOW=now_str, USER_PROFILE=user_profile)


chat_model = ChatOpenAI(
    base_url="http://localhost:8000/v1",
    api_key=settings.OPENAI_API_KEY,
    model=settings.MODEL_NAME,
    temperature=0.0,
    top_p=0.95,
    streaming=True,
    stream_usage=True,
    verbose=True,
    seed=42
)

summarize_model = ChatOpenAI(
    base_url="http://localhost:8000/v1",
    api_key=settings.OPENAI_API_KEY,
    model=settings.MODEL_NAME,
    temperature=0.0,
    top_p=0.95,
)

agent = create_agent(
    model=chat_model,
    tools=[save_user_info, db_assistant],
    checkpointer=get_checkpointer(),
    store=get_store(),
    middleware=[
        build_system_prompt,
        SummarizationMiddleware(
            model=summarize_model,
            trigger=[("tokens", 4096), ("messages", 6)],
            keep=("messages", 10)
        ),
        PIIMiddleware("credit_card", strategy="mask", apply_to_input=True)
    ]
)

__all__ = ["agent"]