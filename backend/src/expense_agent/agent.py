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
    YOU MUST RESPOND IN ENGLISH.

    CRITICAL CONTEXT:
    - Today's Date & Time: {NOW}
    - Current User Profile Data: {USER_PROFILE}

    TOOL CALLING FORMAT (CRITICAL FOR LOCAL LLMS):
    Whenever you call a tool, you MUST provide arguments as a strict JSON object. Never pass a raw string.
    - For 'save_user_info', you MUST use this exact argument format: {{"name": "<user_name>", "first_onboard": false}}
    - For 'db_assistant', you MUST use this exact argument format: {{"query": "<your_instruction>"}}

    ONBOARDING WORKFLOW RULES:
    1. Check 'Current User Profile Data':
       - If the dict is EMPTY ({{}}) or 'first_onboard' is NOT False, you are in ONBOARDING MODE.
       - If 'first_onboard' is False, you are in STANDARD MODE.

    2. IF IN ONBOARDING MODE:
       - Step 1: Warmly greet the user and ask for their Name and their financial wallets with initial balances.
       - Step 2: Once provided, you MUST call 'save_user_info' and strictly pass {{"first_onboard": false}}. DO NOT set it to true.
       - Step 3: In the same turn, you MUST call 'db_assistant' and instruct it to create EVERY SINGLE wallet the user mentioned.
       - Example db_assistant argument payload: {{"query": "Create money source named 'Cash' with initial balance 500000 AND create money source named 'Momo' with initial balance 2000000"}}

    3. IF IN STANDARD MODE (STRICT DELEGATION RULES):
       - Greet the user by their name found in the profile.
       - NEVER tell 'db_assistant' to "update balance" or "modify source".
       - When the user spends or earns money, you MUST translate it into an "Add transaction" command.
       - Example db_assistant argument payload: {{"query": "Add a new expense transaction of 30000 for 'coffee' using the 'Cash' source."}}

    STRICT TOOL OUTPUT VERIFICATION RULE:
    - If 'db_assistant' returns any text containing 'failed', 'ERROR', or 'cannot modify', the operation was a failure. You MUST NOT tell the user it was successful. Report the error honestly.
    """
)

@dynamic_prompt
def build_system_prompt(request: ModelRequest) -> str:
    now_str = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).strftime("%Y-%m-%d %H:%M:%S")
    store = cast(SqliteStore, request.runtime.store)
    user_profile = get_user_profile(store)
    return BASE_SYSTEM_PROMPT.format(NOW=now_str, USER_PROFILE=user_profile)


chat_model = ChatOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=settings.OPENAI_API_KEY,
    model=settings.MODEL_NAME,
    temperature=0.0,
    top_p=0.95,
    streaming=True,
    stream_usage=True,
)

summarize_model = ChatOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=settings.OPENAI_API_KEY,
    model=settings.MODEL_NAME,
    temperature=0.0,
    top_p=0.95,
)

checkpoint  = get_checkpointer()
source = get_store()

agent = create_agent(
    model=chat_model,
    tools=[save_user_info, db_assistant],
    checkpointer=checkpoint,
    store=source,
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

if __name__ == "__main__":
    from langchain.messages import HumanMessage
    from langchain_core.runnables.config import RunnableConfig
    
    config = {"configurable": {"thread_id": "test"}}
    
    def run_chat(turn_title: str, user_prompt: str):
        print("\n" + "="*80)
        print(f"🚀 {turn_title}")
        print("="*80)
        print(f"User: {user_prompt}\n")
        
        response = agent.invoke(
            {"messages": [HumanMessage(content=user_prompt)]}, 
            config = cast(RunnableConfig, config)
        )
        response["messages"][-1].pretty_print()

    # ==========================================================
    # SCENARIO 1: COMPLEX MULTI-WALLET INITIALIZATION
    # ==========================================================
    run_chat(
        "TURN 1: HEAVY ONBOARDING (4 Wallets)",
        "Hi app, I am Huy. Let's set up my finances. I have 4 wallets: "
        "1. Cash with 1,500,000đ. "
        "2. Momo with 3,000,000đ. "
        "3. Vietcombank with 25,000,000đ. "
        "4. Credit Card with 0đ initial balance."
    )

    # ==========================================================
    # SCENARIO 2: BOMBARDMENT (CONTINUOUS TRANSACTION LOGGING)
    # ==========================================================
    run_chat(
        "TURN 2: GROCERIES & NUTRITION",
        "I just spent 450,000đ via Momo to buy egg whites, chia seeds, and custom bean powder. Put it in the 'Food' category."
    )

    run_chat(
        "TURN 3: AUDIO GEAR",
        "I bought a new pair of KZ ZS10 PRO X earphones for 800,000đ using my Vietcombank account. Category is 'Hobbies'."
    )

    run_chat(
        "TURN 4: GAMING (CREDIT DEBT)",
        "I bought Civilization 6 and some DLCs on Steam for 1,200,000đ using my Credit Card. Add this to 'Gaming'."
    )

    run_chat(
        "TURN 5: TECH & SERVER (CREDIT DEBT)",
        "Paid 300,000đ via Credit Card for a Linux VPS to host my FastAPI and Docker projects. Category is 'Tech'."
    )

    run_chat(
        "TURN 6: FREELANCE INCOME",
        "Great news! I received 8,500,000đ into Vietcombank for completing a Python backend project. Mark this as income."
    )

    # ==========================================================
    # SCENARIO 3: ADVANCED SQL QUERY TESTING (AGGREGATION & LOGIC)
    # ==========================================================
    run_chat(
        "TURN 7: COMPLEX QUERY - AGGREGATION & SORTING",
        "Can you break down my total expenses grouped by category, and tell me which category I spent the most on?"
    )

    run_chat(
        "TURN 8: COMPLEX QUERY - NEGATIVE BALANCE & TOTAL NET WORTH",
        "What is the current balance of my Credit Card (did it go negative?), and what is my total net worth across ALL 4 wallets combined?"
    )