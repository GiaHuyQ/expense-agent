import inspect
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_openai.chat_models import ChatOpenAI
from langchain.messages import HumanMessage
from langchain.agents import create_agent
from langchain.tools import tool, ToolRuntime
from langchain.agents.middleware import dynamic_prompt, ModelRequest

from src.expense_agent.config import settings
from src.expense_agent.logging_config import logger
from src.expense_agent.sql_agent.tools import (
    get_db_dictionary,
    execute_sql,
    add_transaction,
    update_transaction,
    delete_transaction,
    add_category,
    add_money_source,
)

# Crucial System Prompt instructing the LLM on deterministic Text-to-SQL workflows
BASE_SYSTEM_PROMPT = inspect.cleandoc("""You are a precise SQLite Expert and Financial Assistant for an Expense Tracker app.
Your core mission is to help users read, add, update, or delete transactions accurately.

CONTEXT:
- Today: {NOW}. This is a literal date value — substitute it directly into SQL (e.g. if {NOW} is '2026-06-25', write date('2026-06-25', ...), never date('{NOW}', ...)).

CRITICAL MANDATE - ZERO GUESSING (STRICTLY ENFORCED):
1. THE ABSOLUTE FIRST STEP: You MUST ALWAYS invoke the 'get_db_dictionary' tool BEFORE doing anything else. Never assume you know the table or column names.
2. Read and strictly follow the 'rules_and_guidelines' returned by 'get_db_dictionary'.
3. ANTI-HALLUCINATION WARNING: YOU MUST USE THE ACTUAL FUNCTION-CALLING API TO INVOKE TOOLS. NEVER write simulated tool calls in plain text or markdown blocks (e.g., DO NOT write `Tool call: get_db_dictionary()` or ````sql ADD TRANSACTION()````). Writing fake code blocks fails the system.

MUTATION WORKFLOW (FOR ADDING/UPDATING/DELETING):
1. Call 'get_db_dictionary' via the tool API.
2. Run 'execute_sql' (SELECT only) to find the correct 'source_id' and 'category_id'.
3. Call 'add_category' if the category is missing.
4. Call 'add_transaction' (or update/delete). The database calculates the 'current_balance' dynamically via views.
5. WARNING: NEVER manually update wallet balances. NEVER use UPDATE/INSERT/DELETE on 'source' or 'source_balance'. The 'execute_sql' tool is STRICTLY for 'SELECT' queries.

STRICT HANDOVER & FINAL ANSWER RULES:
- Use the read-only 'source_balance' view ONLY for reading balances via SELECT (e.g., SELECT current_balance FROM source_balance).
- DO NOT display or output raw SQL query blocks (like SELECT, UPDATE, INSERT) in your final response to the user.
- YOU MUST RESPOND TO THE USER IN ENGLISH.

CONCEPTUAL EXAMPLE WORKFLOW (Do not output these steps as text, execute them as real JSON tool calls!):
- User: "I spent 30k for coffee using Cash."
- Step 1: You ACTUALLY INVOKE the 'get_db_dictionary' tool.
- Step 2: You ACTUALLY INVOKE the 'execute_sql' tool to find IDs for 'Cash' and 'coffee'.
- Step 3: You ACTUALLY INVOKE the 'add_transaction' tool with amount=30000.
- Step 4: You reply to the user: "I have successfully logged your expense of 30,000đ for a cup of coffee from your Cash wallet."
""")

model = ChatOpenAI(
    base_url="https://openrouter.ai/api/v1/",
    api_key=settings.OPENAI_API_KEY,
    model=settings.MODEL_NAME,
    temperature=0.0,
    top_p=0.95,
)

@dynamic_prompt
def build_system_prompt(request: ModelRequest) -> str:
    now_str = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).strftime("%Y-%m-%d %H:%M:%S")
    return BASE_SYSTEM_PROMPT.format(NOW=now_str)

sql_agent = create_agent(
    model=model,
    middleware=[build_system_prompt], 
    tools=[get_db_dictionary, execute_sql, add_category, add_money_source, add_transaction, update_transaction, delete_transaction]
)

@tool
def db_assistant(query: str, runtime: ToolRuntime) -> str:
    """Assistant specialized in financial expense tracking data.

    Call this tool whenever the user wants to inquire about wallet balances,
    net worth, transaction history, or wants to add, update, or delete
    expense/income records.

    Args:
        query: The raw natural language instruction or question from the user,
            passed through as-is for the specialized assistant to interpret.
    """
    logger.info(f"finance_db_assistant_triggered | query='{query}'")
    try:
        response = sql_agent.invoke(
            {"messages": [HumanMessage(content=query)]},
            store=runtime.store
        )
        return str(response["messages"][-1].content)
    except Exception as err:
        logger.error(f"finance_db_assistant_failed | error='{str(err)}'")
        return "ERROR: The financial assistant encountered an error"