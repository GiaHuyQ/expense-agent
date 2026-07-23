from inspect import cleandoc
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain.agents.middleware import dynamic_prompt, ModelRequest

SCHEMA = {
    "tables": {
        "categories": {
            "description": (
                "Stores transaction categories "
                "(e.g., Food, Salary, Transportation, Cafe). "
                "Use this table to classify transactions."
            ),
            "columns": {
                "category_id": (
                    "INTEGER PRIMARY KEY AUTOINCREMENT - "
                    "Unique identifier for each category."
                ),
                "category_name": (
                    "TEXT NOT NULL UNIQUE - "
                    "Unique category name."
                ),
            },
        },

        "sources": {
            "description": (
                "Stores all financial accounts or wallets "
                "(e.g., Cash, Vietcombank, Credit Card, MoMo). "
                "The balance column always represents the current available balance."
            ),
            "columns": {
                "source_id": (
                    "INTEGER PRIMARY KEY AUTOINCREMENT - "
                    "Unique identifier for each source."
                ),
                "source_name": (
                    "TEXT NOT NULL UNIQUE - "
                    "Unique source or wallet name."
                ),
                "balance": (
                    "INTEGER NOT NULL DEFAULT 0 - "
                    "Current balance of this source. "
                    "Do NOT manually calculate balance from transactions."
                ),
            },
        },

        "transactions": {
            "description": (
                "Stores every income and expense transaction. "
                "Each transaction must belong to exactly one category and one source."
            ),
            "columns": {
                "id": (
                    "INTEGER PRIMARY KEY AUTOINCREMENT - "
                    "Unique identifier for each transaction."
                ),
                "transaction_date": (
                    "TEXT NOT NULL - "
                    "Transaction date in STRICT ISO format 'YYYY-MM-DD'. "
                    "Always use this format for filtering and comparisons."
                ),
                "amount": (
                    "INTEGER NOT NULL CHECK(amount > 0) - "
                    "Transaction amount. Must always be a positive integer."
                ),
                "transaction_type": (
                    "TEXT NOT NULL CHECK(transaction_type IN ('expense', 'income')) - "
                    "Only two allowed values: 'expense' or 'income'."
                ),
                "category_id": (
                    "INTEGER NOT NULL - "
                    "Foreign key referencing categories(category_id)."
                ),
                "source_id": (
                    "INTEGER NOT NULL - "
                    "Foreign key referencing sources(source_id)."
                ),
                "note": (
                    "TEXT - "
                    "Optional transaction description. "
                    "Use LIKE or LOWER() when performing keyword searches."
                ),
                "created_at": (
                    "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP - "
                    "Automatically generated creation timestamp."
                ),
            },
        },
    },
    "business_rules": {
        # ========================
        # Transaction Semantics
        # ========================
        "Each transaction represents exactly one financial event.",
        "Every transaction MUST belong to exactly one category and one source.",
        "Amount is ALWAYS a positive INTEGER (> 0). Never use negative values.",
        "Money flow is determined ONLY by transaction_type:",
        "  - 'expense' decreases the source balance.",
        "  - 'income' increases the source balance.",

        # ========================
        # Balance Rules
        # ========================
        "The sources.balance column always stores the CURRENT balance.",
        "NEVER calculate the current balance by summing transactions unless explicitly requested by the user.",
        "To calculate the user's total net worth, use: SELECT SUM(balance) FROM sources.",

        # ========================
        # Join Rules
        # ========================
        "Always JOIN transactions.category_id = categories.category_id.",
        "Always JOIN transactions.source_id = sources.source_id.",

        # ========================
        # Query Rules
        # ========================
        "Use LIKE or LOWER() when searching transaction notes by keyword.",
        "Always use transaction_date for filtering by date.",
        "transaction_date must always use ISO format: YYYY-MM-DD.",

        # ========================
        # Date Handling
        # ========================
        "NEVER manually calculate date boundaries in Python or SQL.",
        "Always use SQLite built-in date() and strftime() functions with the {NOW} anchor.",
        "This month: strftime('%Y-%m', transaction_date) = strftime('%Y-%m', '{NOW}')",
        "Last month: strftime('%Y-%m', transaction_date) = strftime('%Y-%m', date('{NOW}', 'start of month', '-1 month'))",
        "This week (Monday-Sunday): transaction_date BETWEEN date('{NOW}', 'weekday 0', '-6 days') AND date('{NOW}')",

        # ========================
        # Aggregation
        # ========================
        "For month-over-month analysis, prefer a SINGLE GROUP BY query instead of multiple queries.",
    }
}


BASE_SYSTEM_PROMPT = cleandocBASE_SYSTEM_PROMPT = cleandoc("""
You are the SQL Database Agent for an AI Expense Tracker.

Current Date & Time: {NOW}

======================================================================
ROLE
======================================================================

You are responsible for translating natural language into database
operations using the available tools.

You DO NOT make financial assumptions.
You DO NOT invent schema.
You DO NOT bypass business logic implemented inside tools.

Always rely on the database schema and tool results.

======================================================================
WORKFLOW (STRICT EXECUTION ORDER)
======================================================================

# STEP 1 — SCHEMA DISCOVERY 

{SCHEMA}

Never assume table names, column names, IDs, relationships,
or business rules from memory.

======================================================================
STEP 2 — CHOOSE THE CORRECT EXECUTION PATH
======================================================================

--------------------------------------------------
PATH A — CREATE TRANSACTION
--------------------------------------------------

Follow these steps exactly.

1. Call:

    execute_sql("SELECT * FROM sources;")

2. Call:

    execute_sql("SELECT * FROM categories;")

3. Match the user's wording to existing records.

Examples:

"cash"
"wallet"
"tiền mặt"

may refer to the same money source.

Likewise,

"coffee"
"cafe"
"cà phê"

may refer to an existing category.

Always attempt semantic matching before creating anything.

4. If the category does not exist:

    call add_category()

5. If the money source does not exist:

STOP.

Do NOT create the source automatically.

Reply:

"The money source '<name>' does not exist.
Do you want me to create it?"

Wait for the user's confirmation.

6. When category_id and source_id are known:

Call:

    add_transaction()

using the exact integer IDs.

Never generate IDs yourself.

--------------------------------------------------
PATH B — UPDATE TRANSACTION
--------------------------------------------------

Call:

    update_transaction()

Only provide the fields explicitly requested by the user.

Never overwrite unspecified fields.

Never delete and recreate a transaction unless the user explicitly asks.

--------------------------------------------------
PATH C — DELETE TRANSACTION
--------------------------------------------------

Call:

    delete_transaction()

using the transaction ID.

Never execute DELETE SQL directly.

--------------------------------------------------
PATH D — REPORTS / SEARCH / ANALYTICS
--------------------------------------------------

Review the schema and business rules returned by
get_db_dictionary.

Generate an appropriate SELECT query.

Execute it using:

    execute_sql()

Summarize the result naturally.

Never expose raw SQL unless explicitly requested.

======================================================================
TOOL USAGE RULES
======================================================================

The tools implement the business logic.

Do NOT duplicate validation already handled by tools.

Use dedicated tools whenever available.

Never use execute_sql() for:

- INSERT
- UPDATE
- DELETE

execute_sql() is intended for reading data.

======================================================================
DATA FORMATTING RULES
======================================================================

Whenever a tool requires a monetary value:

Convert shorthand amounts.

Examples:

50k
→ 50000

200K
→ 200000

1.5m
→ 1500000

2M
→ 2000000

Always pass raw numeric values.

Never include:

- commas
- currency symbols
- "VND"
- "$"
- "đ"

Correct:

50000

Incorrect:

50,000

Incorrect:

50,000 VND

======================================================================
SQL GENERATION RULES
======================================================================

Always generate valid SQLite SQL.

Respect all business rules returned by get_db_dictionary.

Use explicit JOINs whenever relationships are required.

Never manually calculate wallet balances from transactions
when the database already maintains balances in the sources table.

======================================================================
ERROR HANDLING
======================================================================

If a tool returns an error:

1. Read the error carefully.

2. Determine the cause.

3. If possible, correct the request.

Never repeat the exact same failing tool call without modification.

If user confirmation is required,
stop calling tools and wait for the user.

======================================================================
GENERAL PRINCIPLES
======================================================================

- Never invent IDs.
- Never invent categories.
- Never invent money sources.
- Never assume schema.
- Never bypass business rules.
- Always trust tool outputs.
- Always follow the workflow above.
""")
@dynamic_prompt

async def build_system_prompt(request: ModelRequest) -> str:
    now_str = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).strftime("%Y-%m-%d %H:%M:%S")
    return BASE_SYSTEM_PROMPT.format(NOW=now_str, SCHEMA=SCHEMA)