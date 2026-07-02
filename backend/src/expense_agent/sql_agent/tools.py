import aiosqlite
from typing import Any
from datetime import datetime

from src.expense_agent.logging_config import logger
from langchain.tools import tool
from langchain_core.runnables import RunnableConfig

@tool
def get_db_dictionary() -> dict:
    """Retrieve the comprehensive database dictionary containing tables, columns, constraints, and views."""
    data_dictionary = {
        "tables": {
            "category": {
                "description": "Stores transaction categories (e.g., Food, Salary, Cafe). Use this table to group or filter transactions by category name.",
                "columns": {
                    "category_id": "INTEGER PRIMARY KEY - Unique identifier for each category.",
                    "category_name": "TEXT NOT NULL UNIQUE - The name of the category. Always unique."
                }
            },
            "source": {
                "description": "Stores financial accounts or money sources (e.g., Cash, Vietcombank, Credit Card).",
                "columns": {
                    "source_id": "INTEGER PRIMARY KEY - Unique identifier for each wallet/source.",
                    "source_name": "TEXT NOT NULL UNIQUE - The name of the payment or income source.",
                    "initial_balance": "REAL NOT NULL DEFAULT 0 - The starting balance of the source before any recorded transactions."
                }
            },
            "transactions": {
                "description": "Records all financial movements (incomes and expenses). Connects categories and sources.",
                "columns": {
                    "id": "INTEGER PRIMARY KEY - Unique identifier for each transaction.",
                    "transaction_date": "TEXT NOT NULL - Date of the transaction. STRICT FORMAT: 'YYYY-MM-DD' (e.g., '2026-06-25'). Always query or filter using this ISO format.",
                    "amount": "REAL NOT NULL - The money value. Must be strictly greater than 0.",
                    "transaction_type": "TEXT NOT NULL - Type of transaction. Allowed values: STRICTLY ONLY 'expense' (for spending) or 'income' (for earnings).",
                    "category_id": "INTEGER - Foreign key referencing category(category_id). Can be NULL.",
                    "source_id": "INTEGER - Foreign key referencing source(source_id). Can be NULL.",
                    "note": "TEXT - Optional description or details about the transaction. Use LIKE or lower() operator for keyword searching.",
                    "created_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP - Automatically set to the current timestamp when the record is created." 
                }
            }
        },
        "views": {
            "source_balance": {
                "description": "A read-only virtual table providing real-time current balances. DO NOT insert or update this view. Formula: current_balance = initial_balance + sum(income) - sum(expense). Use this view directly whenever the user asks for 'current balance', 'how much money left', or 'total money'.",
                "columns": {
                    "source_id": "INTEGER - Inherited from source table.",
                    "source_name": "TEXT - Inherited from source table.",
                    "current_balance": "REAL - The net real-time balance calculated dynamically across all transactions."
                }
            }
        },
        "rules_and_guidelines": [
            "To calculate total net worth or total remaining money across all wallets, use 'SELECT SUM(current_balance) FROM source_balance;'",
            "Always perform explicit JOINs using foreign key constraints: transactions.category_id = category.category_id and transactions.source_id = source.source_id.",
            "NEVER manually compute date boundaries (start/end of month/week) — always use SQLite's built-in date()/strftime() functions on top of the {NOW} anchor, to avoid off-by-one or year-rollover errors:",
            "  - This month: strftime('%Y-%m', date) = strftime('%Y-%m', '{NOW}')",
            "  - Last month: strftime('%Y-%m', date) = strftime('%Y-%m', date('{NOW}', 'start of month', '-1 month'))",
            "  - This week (Mon-Sun): date BETWEEN date('{NOW}', 'weekday 0', '-6 days') AND date('{NOW}')",
            "For month-over-month comparisons, prefer a SINGLE query with GROUP BY strftime('%Y-%m', date) and a WHERE clause covering both months — this avoids running two separate queries and re-joining results manually.",
        ]
    }
    return data_dictionary

@tool
async def execute_sql(query: str, config: RunnableConfig) -> dict[str, object]:
    """Execute a read-only SQL query.

    Args:
        query: SQL query.
    """
    db = config.get("configurable", {}).get("db")

    if not db:
        logger.error("Database connection missing in config")
        return {"status": "error", "message": "System error: DB not connected."}

    logger.info("execute_sql_called | query=%s", query)

    conn = db.read_conn

    try:
        cursor = await conn.execute(query)

        results = await cursor.fetchall()
    
        if not results:
            return {
                "status": "success",
                "rows": []
            }
        
        rows = [dict(row) for row in results]   

        return {
            "status": "success",
            "rows": rows
        }
    
    except aiosqlite.Error:
        logger.exception("execute_sql_failed | query=%s", query)
        return {"status": "error"}
    
@tool
async def add_category(category_name: str, config: RunnableConfig) -> dict[str, object]:
    """Create a category if it does not exist.

    Args:
        category_name: Category name.
    """
    db = config.get("configurable", {}).get("db")

    if not db:
        logger.error("Database connection missing in config")
        return {"status": "error", "message": "System error: DB not connected."}

    logger.info("add_category_called | category_name=%s", category_name)

    conn = db.write_conn

    try:      
        # Insert or ignore if it already exists due to UNIQUE constraint
        await conn.execute(
            "INSERT OR IGNORE INTO category (category_name) VALUES (?);", 
            (category_name,),
        )

        await conn.commit()
        
        return {
            "status": "success",
            "category_name": category_name,
        }
    
    except aiosqlite.Error:
        await conn.rollback()
        logger.exception(
            "add_category_failed | category_name=%s",
            category_name,
        )

        return {
            "status": "error",
        }

@tool
async def add_money_source(
        config: RunnableConfig,
        source_name: str, 
        initial_balance: float = 0.0,
    ) -> dict[str, str]:
    """Create a money source if it does not exist.

    Args:
        source_name: Money source name.
        initial_balance: Initial balance.
    """
    db = config.get("configurable", {}).get("db")

    if not db:
        logger.error("Database connection missing in config")
        return {"status": "error", "message": "System error: DB not connected."}

    logger.info(
        "add_money_source_called | source_name=%s | initial_balance=%s",
        source_name,
        initial_balance,
    )

    conn = db.write_conn

    try:

        await conn.execute(
            "INSERT OR IGNORE INTO source (source_name, initial_balance) VALUES (?, ?);", 
            (source_name, initial_balance)
        )

        await conn.commit()

        logger.info(
            "add_money_source_success | source_name=%s",
            source_name,
        )

        return {
            "status": "success",
            "source_name": source_name
        }

    except aiosqlite.Error:
        await conn.rollback()
        logger.exception(
            "add_money_source_failed | source_name=%s",
            source_name,
        )
        return {"status": "error"}


@tool
async def add_transaction(
    config: RunnableConfig,
    transaction_date: str, 
    amount: float, 
    transaction_type: str, 
    category_id: int, 
    source_id: int,
    note: str | None = None) -> dict[str, Any]:
    """Add a new transaction strictly using pre-validated integer category_id and source_id.

    Args:
        transaction_date: The date string formatted strictly as 'YYYY-MM-DD'.
        amount: The monetary value, must be strictly greater than 0.
        transaction_type: Strictly either 'expense' or 'income'.
        category_id: The verified integer ID of the category.
        source_id: The verified integer ID of the money source.
        note: Optional description text for the transaction details.
    """
    transaction_type = transaction_type.lower()

    if transaction_type not in {"expense", "income"}:
        return {
            "status": "error",
            "message": "Invalid transaction type."
        }

    if amount <= 0:
        return {
            "status": "error",
            "message": "Amount must be greater than zero."
        }
    
    try:
        datetime.strptime(transaction_date, "%Y-%m-%d")
    except ValueError:
        return {
            "status": "error",
            "message": (
                "Invalid transaction date. "
                "Expected format: YYYY-MM-DD."
            )
        }

    db = config.get("configurable", {}).get("db")

    if not db:
        logger.error("Database connection missing in config")
        return {"status": "error", "message": "System error: DB not connected."}

    logger.info(
        "add_transaction_called | date=%s | amount=%s | "
        "type=%s | category_id=%s | source_id=%s",
        transaction_date,
        amount,
        transaction_type,
        category_id,
        source_id,
    )

    conn = db.write_conn

    try:
        # Secure parameterized insertion
        cursor = await conn.execute(
            """
            INSERT INTO transactions (transaction_date, amount, transaction_type, category_id, source_id, note)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (transaction_date, amount, transaction_type, category_id, source_id, note)
        )

        await conn.commit()

        transaction_id = cursor.lastrowid
        
        logger.info(
            "add_transaction_success | transaction_id=%s",
            transaction_id
        )

        return {
            "status":"success",
            "transaction_id":transaction_id
        }
    
    except aiosqlite.Error:
        await conn.rollback()
        logger.exception("add_transaction_failed")
        return {"status":"error"}

@tool
async def update_transaction(
    config: RunnableConfig,
    transaction_id: int, 
    transaction_date: str | None = None, 
    amount: float | None = None, 
    transaction_type: str | None = None, 
    category_id: int | None = None, 
    source_id: int | None = None, 
    note: str | None = None) -> dict[str, Any]:
    """Update specific fields of an existing transaction by its unique ID.

    Args:
        transaction_id: The integer primary key ID of the transaction to modify.
        transaction_date: Optional new date string formatted as 'YYYY-MM-DD'.
        amount: Optional new monetary value, must be strictly greater than 0.
        transaction_type: Optional new type, strictly either 'expense' or 'income'.
        category_id: Optional new verified integer ID of the category.
        source_id: Optional new verified integer ID of the money source.
        note: Optional new description text for the transaction.
    """
    db = config.get("configurable", {}).get("db")

    if not db:
        logger.error("Database connection missing in config")
        return {"status": "error", "message": "System error: DB not connected."}

    logger.info("update_transaction_called | transaction_id=%s", transaction_id)

    conn = db.write_conn

    try:
        # 1. Check if the transaction actually exists before attempting an update
        cursor = await conn.execute("SELECT 1 FROM transactions WHERE id = ?;", (transaction_id,))
        
        record = await cursor.fetchone()

        if not record:
            logger.error("update_transaction_failed | id_not_found=%s", transaction_id)
            return {
                "status": "error",
                "content": "transaction_id not found",
                "transaction_id": transaction_id
            }
        
        # 2. Dynamically build the SQL UPDATE statement based on provided arguments
        update_fields = []
        query_params = []

        if transaction_date is not None:
            try:
                datetime.strptime(transaction_date, "%Y-%m-%d")
            except ValueError:
                return {
                    "status": "error",
                    "message": "Invalid transaction date."
                }
            
            update_fields.append("transaction_date = ?")
            query_params.append(transaction_date)

        if amount is not None:
            if amount <= 0:
                return {
                    "status": "error",
                    "message": "transaction amount must be strictly greater than 0."
                }
            
            update_fields.append("amount = ?")
            query_params.append(amount)

        if transaction_type is not None:
            transaction_type = transaction_type.lower()
            
            if transaction_type not in ["expense", "income"]:
                return {
                    "status": "error",
                    "message": "transaction_type must be either 'expense' or 'income'."
                }
            
            update_fields.append("transaction_type = ?")
            query_params.append(transaction_type)

        if category_id is not None:
            update_fields.append("category_id = ?")
            query_params.append(category_id)

        if source_id is not None:
            update_fields.append("source_id = ?")
            query_params.append(source_id)

        if note is not None:
            update_fields.append("note = ?")
            query_params.append(note)

        # If the user called the tool but provided no new data to update
        if not update_fields:
            logger.warning("update_transaction_ignored | no fields provided for update on id=%s", transaction_id)
            return {
                "status": "error",
                "message": "no fields provided for update"
            }

        # Append the transaction_id to the very end of parameter list for the WHERE clause
        query_params.append(transaction_id)
        
        # Join the list into a clean query string: "SET date = ?, amount = ?"
        sql_script = f"UPDATE transactions SET {', '.join(update_fields)} WHERE id = ?;"

        # 3. Securely execute the dynamic parameterized query
        await conn.execute(sql_script, tuple(query_params))
        await conn.commit()

        logger.info(
            "update_transaction_success | transaction_id=%s updated fields=%s",
            transaction_id,
            update_fields
        )
        
        return {
            "status": "success",
            "transaction_id": transaction_id
        }

    except aiosqlite.Error:
        await conn.rollback()
        logger.exception(
            "update_transaction_failed | transaction_id=%s",
            transaction_id
        )
        return {
            "status": "error"
        }

@tool
async def delete_transaction(
    config: RunnableConfig,
    transaction_id: int
) -> dict[str, Any]:
    """Delete an existing transaction permanently from the database by its ID.

    Args:
        transaction_id: The integer primary key ID of the transaction to be removed.
    """
    db = config.get("configurable", {}).get("db")

    if not db:
        logger.error("Database connection missing in config")
        return {"status": "error", "message": "System error: DB not connected."}

    logger.info("delete_transaction_called | transaction_id=%s", transaction_id)

    conn = db.write_conn

    try:
        cursor = await conn.execute(
            "SELECT 1 FROM transactions WHERE id = ?;", 
            (transaction_id,)
        )
        
        record = await cursor.fetchone()
        
        if not record:
            logger.warning(
                "delete_transaction_failed | not found transaction_id=%s", 
                transaction_id
            )
            return {
                "status" : "error",
                "message" : "transaction_id not found",
                "transaction_id": transaction_id
            }

        await conn.execute("DELETE FROM transactions WHERE id = ?;", (transaction_id,))
        await conn.commit()
      
        logger.info("delete_transaction_success | removed transaction_id=%s", transaction_id)
        return {"status": "success"}
    
    except aiosqlite.Error:
        await conn.rollback()
        logger.exception("delete_transaction_failed | transaction_id=%s", transaction_id)
        return {"status": "error"}
    