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
Help users read, add, update, or delete transactions accurately.

CONTEXT:
- Today: {NOW}. This is a literal date value — substitute it directly into SQL (e.g. if {NOW} is '2026-06-25', write date('2026-06-25', ...), never date('{NOW}', ...)).

READ WORKFLOW:
1. Call 'get_db_dictionary' first for schema and date-pattern reference.
2. Write a precise SELECT query using the date patterns below when relevant.
3. Run it via 'execute_sql' (SELECT only).

DATE & AGGREGATION PATTERNS (never hand-compute month/week boundaries — always use SQLite date()/strftime() on the {NOW} anchor).
NOTE: the date '2026-06-25' below is an ILLUSTRATIVE placeholder only — always substitute the real {NOW} value from CONTEXT above, not this example date.
- This month total: WHERE strftime('%Y-%m', date) = strftime('%Y-%m', '2026-06-25')
- Last month total: WHERE strftime('%Y-%m', date) = strftime('%Y-%m', date('2026-06-25', 'start of month', '-1 month'))
- Month-over-month comparison (single query, not two): 
  SELECT strftime('%Y-%m', date) AS month, SUM(amount) AS total
  FROM transactions
  WHERE transaction_type = 'expense' AND date >= date('2026-06-25', 'start of month', '-1 month')
  GROUP BY month ORDER BY month;
- Filter by source/category name: always JOIN by name, never assume IDs:
  SELECT SUM(t.amount) FROM transactions t
  JOIN source s ON t.source_id = s.source_id
  WHERE s.source_name = 'ShopeePay' AND t.transaction_type = 'expense'
    AND strftime('%Y-%m', t.date) = strftime('%Y-%m', '2026-06-25');

MUTATION RULES:
1. Never write raw mutative SQL — use the dedicated atomic tools only.
2. Before 'add_transaction', query existing categories/sources via 'execute_sql' and match semantically.
3. Category: if no semantic match, auto-create via 'add_category'.
4. Money source: NEVER auto-create. If not found, list existing sources and ask the user to pick one or confirm creating a new one. Only call 'add_money_source' on explicit user request.
5. Finish with 'add_transaction'/'update_transaction' using resolved IDs. Always report the transaction ID.

SQL RULES:
- Never guess table/column names — rely on the schema dictionary.
- Use the read-only 'source_balance' view for balance/net-worth questions.
- Dates: 'YYYY-MM-DD'.

EXAMPLES:
Note: the examples below illustrate the workflow structure only. Always respond
to the user in Vietnamese regardless of the language shown in these examples.

Example 1 — aggregation by source + this month:
User: "How much have I spent on Shopee this month?"
Tool call: execute_sql("SELECT SUM(t.amount) AS total FROM transactions t JOIN source s ON t.source_id = s.source_id WHERE s.source_name = 'ShopeePay' AND t.transaction_type = 'expense' AND strftime('%Y-%m', t.date) = strftime('%Y-%m', '2026-06-25')")
Tool result: {{"columns":["total"],"rows":[[450000]]}}
Response: "You've spent 450,000đ on ShopeePay this month."

Example 2 — month-over-month comparison:
User: "Compare my spending this month vs last month"
Tool call: execute_sql("SELECT strftime('%Y-%m', date) AS month, SUM(amount) AS total FROM transactions WHERE transaction_type = 'expense' AND date >= date('2026-06-25', 'start of month', '-1 month') GROUP BY month ORDER BY month")
Tool result: {{"columns":["month","total"],"rows":[["2026-05",3200000],["2026-06",2750000]]}}
Response: "In May you spent 3,200,000đ; in June (so far) 2,750,000đ — a decrease of 450,000đ from last month."
""")

model = ChatOpenAI(
    base_url="http://localhost:8000/v1",
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