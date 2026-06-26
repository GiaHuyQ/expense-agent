from src.expense_agent.db import get_connection
from src.expense_agent.config import settings
from src.expense_agent.logging_config import logger

from langchain.tools import tool
import sqlite3
import json

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
                    "date": "TEXT NOT NULL - Date of the transaction. STRICT FORMAT: 'YYYY-MM-DD' (e.g., '2026-06-25'). Always query or filter using this ISO format.",
                    "amount": "REAL NOT NULL - The money value. Must be strictly greater than 0.",
                    "transaction_type": "TEXT NOT NULL - Type of transaction. Allowed values: STRICTLY ONLY 'expense' (for spending) or 'income' (for earnings).",
                    "note": "TEXT - Optional description or details about the transaction. Use LIKE or lower() operator for keyword searching.",
                    "category_id": "INTEGER - Foreign key referencing category(category_id). Can be NULL.",
                    "source_id": "INTEGER - Foreign key referencing source(source_id). Can be NULL."
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

def get_readonly_connection():
    """Open read-only connection, SQLite automatically reject all WRITE command in driver"""
    return sqlite3.connect(f"file:{settings.DATA_DIR}/expense.db?mode=ro", uri=True)

@tool
def execute_sql(sql_query: str) -> str:
    """Execute a validated SQLite SELECT query string to read data.

    Args:
        sql_query: The validated SQL SELECT statement string to run.
    """
    logger.info(f"execute_sql_called | query='{sql_query}'")
    conn = get_readonly_connection()
    try:
        cursor = conn.execute(sql_query)
        results = cursor.fetchall()
        headers = [description[0] for description in cursor.description]
    
        if not results:
            return "Execution complete: No records matched"

        payload = {
            "columns": headers,
            "rows": [list(row) for row in results],
        }

        compact = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)

        return f"SUCCESS ({len(results)} rows): {compact}"
    
    except sqlite3.Error as err:
        logger.error(f"execute_sql_failed | error='{str(err)}'")
        return "EXECUTION ERROR: Failed to run query."
    
    finally:
        conn.close()

@tool
def add_category(category_name: str) -> str:
    """Create a new transaction category in the database if it does not exist.

    Args:
        category_name: The name of the category to create (e.g., 'Cafe', 'Shopping').
    """
    logger.info(f"add_category_called | category_name='{category_name}'")
    conn = get_connection()
    try:
        cursor = conn.cursor()
        
        # Insert or ignore if it already exists due to UNIQUE constraint
        cursor.execute(
            "INSERT OR IGNORE INTO category (category_name) VALUES (?);", 
            (category_name,)
        )
        conn.commit()
        
        # Retrieve the ID (either newly created or existing)
        row = conn.execute("SELECT category_id FROM category WHERE category_name = ?;", (category_name,)).fetchone()
        return f"SUCCESS: Category '{category_name}' is ready. ID: {row[0]}."
    
    except sqlite3.Error as err:
        logger.error(f"add_category_failed | error='{str(err)}'")
        return "DATABASE ERROR: Failed to create category."
    
    finally:
        conn.close()


@tool
def add_money_source(source_name: str, initial_balance: float = 0.0) -> str:
    """Create a new financial money source (wallet/account) in the database. 
    
    ONLY call this tool if the user explicitly requests or gives permission to create a new wallet.

    Args:
        source_name: The name of the source to create (e.g., 'Momo', 'Vietcombank').
        initial_balance: The initial starting balance, defaults to 0.0.
    """
    logger.info(f"add_money_source_called | source_name='{source_name}' | initial_balance={initial_balance}")
    conn = get_connection()
    try:
        cursor = conn.cursor()
        
        # Check if it already exists to prevent duplicate failures
        existing = conn.execute("SELECT source_id FROM source WHERE source_name = ?;", (source_name,)).fetchone()

        if existing:
            logger.info(f"add_money_source_ignored | source '{source_name}' already exists.")
            return f"INFO: Money source '{source_name}' already exists with ID: {existing[0]}."
        
        # Strict insertion
        cursor.execute(
            "INSERT INTO source (source_name, initial_balance) VALUES (?, ?);", 
            (source_name, initial_balance)
        )

        conn.commit()
        
        new_id = cursor.lastrowid

        logger.info(f"add_money_source_success | new_id={new_id} | source_name='{source_name}'")
        return f"SUCCESS: New money source '{source_name}' has been created successfully. ID: {new_id}."
    
    except sqlite3.Error as err:
        logger.error(f"add_money_source_failed | error='{str(err)}'")
        return "DATABASE ERROR: Failed to create money source."
    
    finally:
        conn.close()

@tool
def add_transaction(date: str, amount: float, transaction_type: str, category_id: int, source_id: int, note: str | None = None) -> str:
    """Add a new transaction strictly using pre-validated integer category_id and source_id.

    Args:
        date: The date string formatted strictly as 'YYYY-MM-DD'.
        amount: The monetary value, must be strictly greater than 0.
        transaction_type: Strictly either 'expense' or 'income'.
        category_id: The verified integer ID of the category.
        source_id: The verified integer ID of the money source.
        note: Optional description text for the transaction details.
    """
    logger.info(
        f"add_transaction_called | date='{date}' | amount={amount} | "
        f"type='{transaction_type}' | category_id={category_id} | source_id={source_id}"
    )

    conn = get_connection()
    try:
        cursor = conn.cursor()
        
        # Secure parameterized insertion
        cursor.execute(
            """
            INSERT INTO transactions (date, amount, transaction_type, note, category_id, source_id)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (date, amount, transaction_type.lower(), note, category_id, source_id)
        )

        new_id = cursor.lastrowid
        conn.commit()
        
        logger.info(f"add_transaction_success | transaction_id={new_id}")
        return f"SUCCESS: Transaction added successfully. Transaction ID: {new_id}."
    
    except sqlite3.Error as err:
        logger.error(f"add_transaction_failed | error='{str(err)}'")
        return "DATABASE ERROR: Failed to insert transaction."
    
    finally:
        conn.close()

@tool
def update_transaction(
    transaction_id: int, 
    date: str | None = None, 
    amount: float | None = None, 
    transaction_type: str | None = None, 
    category_id: int | None = None, 
    source_id: int | None = None, 
    note: str | None = None) -> str:
    """Update specific fields of an existing transaction by its unique ID.

    Args:
        transaction_id: The integer primary key ID of the transaction to modify.
        date: Optional new date string formatted as 'YYYY-MM-DD'.
        amount: Optional new monetary value, must be strictly greater than 0.
        transaction_type: Optional new type, strictly either 'expense' or 'income'.
        category_id: Optional new verified integer ID of the category.
        source_id: Optional new verified integer ID of the money source.
        note: Optional new description text for the transaction.
    """
    logger.info(f"update_transaction_called | transaction_id={transaction_id}")

    conn = get_connection()
    try:
        # 1. Check if the transaction actually exists before attempting an update
        record = conn.execute("SELECT id FROM transactions WHERE id = ?;", (transaction_id,)).fetchone()
        
        if not record:
            logger.warning(f"update_transaction_failed | id_not_found={transaction_id}")
            return f"ERROR: No transaction found with ID {transaction_id}."
        
        # 2. Dynamically build the SQL UPDATE statement based on provided arguments
        update_fields = []
        query_params = []

        if date is not None:
            update_fields.append("date = ?")
            query_params.append(date)

        if amount is not None:
            if amount <= 0:
                return "ERROR: Transaction amount must be strictly greater than 0."
            
            update_fields.append("amount = ?")
            query_params.append(amount)

        if transaction_type is not None:
            if transaction_type.lower() not in ["expense", "income"]:
                return "ERROR: transaction_type must be either 'expense' or 'income'."
            
            update_fields.append("transaction_type = ?")
            query_params.append(transaction_type.lower())

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
            logger.info(f"update_transaction_ignored | no fields provided for update on id={transaction_id}")
            return f"SUCCESS: No changes were made to transaction ID {transaction_id} (no new values provided)."

        # Append the transaction_id to the very end of parameter list for the WHERE clause
        query_params.append(transaction_id)
        
        # Join the list into a clean query string: "SET date = ?, amount = ?"
        sql_script = f"UPDATE transactions SET {', '.join(update_fields)} WHERE id = ?;"

        # 3. Securely execute the dynamic parameterized query
        conn.execute(sql_script, query_params)
        conn.commit()

        logger.info(f"update_transaction_success | transaction_id={transaction_id} updated fields={update_fields}")
        return f"SUCCESS: Transaction with ID {transaction_id} has been updated successfully."

    except sqlite3.Error as err:
        logger.error(f"update_transaction_failed | id={transaction_id} | error='{str(err)}'")
        return "DATABASE ERROR: Failed to update transaction."
    
    finally:
        conn.close()

@tool
def delete_transaction(transaction_id: int) -> str:
    """Delete an existing transaction permanently from the database by its ID.

    Args:
        transaction_id: The integer primary key ID of the transaction to be removed.
    """
    logger.info(f"delete_transaction_called | transaction_id={transaction_id}")
    conn = get_connection()

    try:
        record = conn.execute("SELECT id FROM transactions WHERE id = ?;", (transaction_id,)).fetchone()
        
        if not record:
            logger.warning(f"delete_transaction_failed | id_not_found={transaction_id}")
            return f"ERROR: No transaction found with ID {transaction_id}."

        conn.execute("DELETE FROM transactions WHERE id = ?;", (transaction_id,))
        conn.commit()
      
        logger.info(f"delete_transaction_success | id={transaction_id} removed")
        return f"SUCCESS: Transaction with ID {transaction_id} has been deleted successfully."
    
    except sqlite3.Error as err:
        logger.error(f"delete_transaction_failed | error='{str(err)}'")
        return "DATABASE ERROR: Failed to delete transaction."
    
    finally:
        conn.close()