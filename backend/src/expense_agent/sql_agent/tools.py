import aiosqlite
from typing import Any
from datetime import datetime

from src.expense_agent.logging_config import logger
from src.expense_agent.db import ExpenseDBResource

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig

def get_db(config: RunnableConfig) -> ExpenseDBResource:
    """Retrieve the ExpenseDBResource from RunnableConfig."""
    db = config.get("configurable", {}).get("db")

    if not db:
        logger.error("Database connection missing in config")
        raise RuntimeError("Database connection missing.")
    
    return db

@tool(description="Retrive data in enxpense database")
async def execute_sql(query: str, config: RunnableConfig) -> dict[str, object]:
    """
    Args:
        query: SQL query.
    """
    try:
        db = get_db(config)
    except RuntimeError:
        return {
            "status": "error",
            "message": "System error"
        }

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
        
        columns = [col[0] for col in cursor.description]

        rows = [dict(zip(columns, row)) for row in results]  

        return {
            "status": "success",
            "rows": rows
        }
    
    except aiosqlite.Error:
        logger.exception("execute_sql_failed | query=%s", query)
        return {"status": "error"}
    
@tool(description="Create one or more expense/income categories if they do not exist.")
async def add_category(category_names: list[str], config: RunnableConfig) -> dict[str, object]:
    """
    Args:
        category_names: List of category names to create. Pass all categories
            the user mentions in a single call instead of calling this tool
            multiple times.
    """
    try:
        db = get_db(config)
    except RuntimeError:
        return {
            "status": "error",
            "message": "System error"
        }

    
    if not category_names:
        return {"status": "error", "message": "No category names provided"}

    logger.info("add_category_called | category_name=%s", category_names)
        
    conn = db.write_conn

    try:      
        # Insert or ignore if it already exists due to UNIQUE constraint
        results = []

        for category in category_names:
            try:
                await conn.execute(
                    "INSERT OR IGNORE INTO categories (category_name) VALUES (?);",
                    (category,),
                )
                results.append({"category_name": category, "status": "success"})

            except aiosqlite.Error as err:
                results.append({"category_name": category, "status": "error", "message": str(err)})

        await conn.commit()
        
        return {
            "status": "success",
            "category_name": results,
        }
    
    except Exception as error:
        await conn.rollback()
        logger.exception(
            "add_category_failed | category_name=%s",
            category_names, error
        )

        return {
            "status": "error",
        }

@tool(description="Create one or more money sources (wallets/accounts) if they do not exist.")
async def add_money_source(
    config: RunnableConfig,
    sources: list[tuple[str, float]],
) -> dict[str, object]:
    """
    Args:
        sources: List of (source_name, initial_balance) pairs to create.
            Pass all money sources the user mentions in a single call
            instead of calling this tool multiple times. Use 0.0 for
            initial_balance if the user does not specify a starting amount.
    """
    try:
        db = get_db(config)
    except RuntimeError:
        return {
            "status": "error",
            "message": "System error"
        }

    if not sources:
        return {"status": "error", "message": "No money sources provided"}

    logger.info("add_money_source_called | sources=%s", sources)
    conn = db.write_conn

    try:
        results = []
        for source_name, initial_balance in sources:
            try:
                await conn.execute(
                    "INSERT OR IGNORE INTO sources (source_name, balance) VALUES (?, ?);",
                    (source_name, initial_balance),
                )
                results.append({"source_name": source_name, "status": "success"})
            except aiosqlite.Error as err:
                results.append({"source_name": source_name, "status": "error", "message": str(err)})

        await conn.commit()
        return {"status": "success", "results": results}

    except aiosqlite.Error:
        await conn.rollback()
        logger.exception("add_money_source_failed | sources=%s", sources)
        return {"status": "error"}


@tool(description="Add a new transaction strictly using pre-validated integer category_id and source_id")
async def add_transaction(
    config: RunnableConfig,
    transaction_date: str, 
    amount: int, 
    transaction_type: str, 
    category_id: int, 
    source_id: int,
    note: str) -> dict[str, Any]:
    """
    Args:
        transaction_date: The date string formatted strictly as 'YYYY-MM-DD'.
        amount: The monetary value, must be strictly greater than 0.
        transaction_type: Strictly either 'expense' or 'income'.
        category_id: The verified integer ID of the category.
        source_id: The verified integer ID of the money source.
        note: Optional description text for the transaction details.
    """

    # 1. Input Validation
    if amount <= 0:
        return {
            "status": "error",
            "message": "Invalid amount"
        }
    
    transaction_type = transaction_type.lower()

    if transaction_type not in {"expense", "income"}:
        return {
            "status": "error",
            "message": "Invalid transaction type"
        }

    try:
        datetime.strptime(transaction_date, "%Y-%m-%d")
    except ValueError:
        return {
            "status": "error",
            "message": (
                "Invalid transaction date"
                "Expected format: YYYY-MM-DD"
            )
        }

    try:
        db = get_db(config)
    except RuntimeError:
        return {
            "status": "error",
            "message": "System error"
        }
    
    conn_r = db.read_conn
    conn_w = db.write_conn

    logger.info(
        "add_transaction_called | date=%s | amount=%s | "
        "type=%s | category_id=%s | source_id=%s",
        transaction_date,
        amount,
        transaction_type,
        category_id,
        source_id,
    )

    try:
        # 2. Begin Transaction
        await conn_w.execute("BEGIN IMMEDIATE")

        # Check Category
        cursor = await conn_r.execute("SELECT 1 FROM categories WHERE category_id = ?", (category_id,))
        
        if await cursor.fetchone() is None:
            await conn_w.rollback()
            return {
                "status": "error",
                "message": "Category not found"
            }
        
        # Check Source
        cursor = await conn_r.execute("SELECT balance FROM sources WHERE source_id = ?", (source_id,))

        # Validate Source
        row = await cursor.fetchone()

        if row is None:
            await conn_w.rollback()
            return {
                "status": "error",
                "message": "Source not found"
            }
        
        current_balance = row[0] # type: ignore
        
        # Business Validation
        if transaction_type == "expense":
            if current_balance < amount:
                await conn_w.rollback()
                return {
                    "status": "error",
                    "message": "Insufficient balance"
                }
            
            new_balance = current_balance - amount
        
        else:
            new_balance = current_balance + amount
            
        # Insert Transaction
        cursor = await conn_w.execute(
            """
            INSERT INTO transactions (transaction_date, amount, transaction_type, category_id, source_id, note)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (transaction_date, amount, transaction_type, category_id, source_id, note)
        )

        transaction_id = cursor.lastrowid

        # Update Balance
        await conn_w.execute(
            "UPDATE sources SET balance = ? WHERE source_id = ?",
            (new_balance, source_id,)                 
        )

        await conn_w.commit()

        logger.info(
            "add_transaction_success | transaction_id=%s",
            transaction_id
        )

        return {
            "status":"success",
            "transaction_id":transaction_id
        }
    
    except aiosqlite.Error:
        await conn_w.rollback()
        logger.exception("add_transaction_failed")
        return {
            "status":"error",
            "message": "Add transaction failed"
        }

FIELDS = (
    "transaction_date",
    "amount",
    "transaction_type",
    "category_id",
    "source_id",
    "note",
)

async def get_old_transaction(conn: aiosqlite.Connection, transaction_id: int) -> dict[str, Any] | None:
    """Get old transaction data by id"""

    try:
        cursor = await conn.execute(
            """
            SELECT
                transaction_date,
                amount,
                transaction_type,
                category_id,
                source_id,
                note
            FROM transactions
            WHERE id = ?
            """,
            (transaction_id,)
        )

        row = await cursor.fetchone()

        if not row:
            raise RuntimeError(
                f"transaction_id {transaction_id} not found."
            )

        return dict(zip(FIELDS, row))

    except aiosqlite.Error:
        logger.exception("Read old transaction_failed")
        raise

async def update_source_balance(conn: aiosqlite.Connection, record: dict[str, Any], reverse: bool = False) -> None:
    """
    Apply or reverse the balance impact of a transaction record.

    If reverse=False:
        expense -> subtract amount
        income  -> add amount

    If reverse=True:
        expense -> add amount
        income  -> subtract amount
    """
    transaction_type = record["transaction_type"]
    source_id = record["source_id"]
    amount = record["amount"]

    try:
        cursor = await conn.execute("SELECT balance FROM sources WHERE source_id = ?", (source_id,))
        row = await cursor.fetchone()
        if not row:
            raise RuntimeError(
                f"transaction_id {source_id} not found."
            )
        
        current_balance = row[0]

        if reverse:
            if transaction_type == "expense":
                new_balance = current_balance + amount
            else:
                new_balance = current_balance - amount
        else:
            if transaction_type == "expense":
                new_balance = current_balance - amount
            else:
                new_balance = current_balance + amount

        await conn.execute("UPDATE sources SET balance = ? WHERE source_id = ?", (new_balance, source_id))

    except aiosqlite.Error:
        logger.exception(
        "update_source_balance_failed | source_id=%s | reverse=%s",
        source_id,
        reverse,
    )
        raise
   
@tool(description="Update specific fields of an existing transaction by its unique ID.")
async def update_transaction(
    config: RunnableConfig,
    transaction_id: int, 
    transaction_date: str | None = None, 
    amount: float | None = None, 
    transaction_type: str | None = None, 
    category_id: int | None = None, 
    source_id: int | None = None, 
    note: str | None = None) -> dict[str, Any]:
    """
    Args:
        transaction_id: The integer primary key ID of the transaction to modify.
        transaction_date: Optional new date string formatted as 'YYYY-MM-DD'.
        amount: Optional new monetary value, must be strictly greater than 0.
        transaction_type: Optional new type, strictly either 'expense' or 'income'.
        category_id: Optional new verified integer ID of the category.
        source_id: Optional new verified integer ID of the money source.
        note: Optional new description text for the transaction.
    """
    try:
        db = get_db(config)
    except RuntimeError:
        return {
            "status": "error",
            "message": "System error"
        }

    logger.info("update_transaction_called | transaction_id=%s", transaction_id)

    conn_w = db.write_conn
    conn_r = db.read_conn
    
    try:
        # 1. Check if the transaction actually exists before attempting an update
        old_record = await get_old_transaction(conn_r, transaction_id)

        if not old_record:
            logger.error("update_transaction_failed | id_not_found=%s", transaction_id)
            return {
                "status": "error",
                "message": "transaction_id not found",
                "transaction_id": transaction_id
            }
        
        
        # 2. Dynamically build the SQL UPDATE statement based on provided arguments
        update_fields = []
        query_params = []

        if amount is not None:
            if amount <= 0:
                return {
                    "status": "error",
                    "message": "Invalid amount"
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
                "message": "No fields provided for update"
            }
        
        # 3. Start transaction
        await conn_w.execute("BEGIN IMMEDIATE")

        # 4. Reverse balance
        await update_source_balance(conn_w, old_record, reverse=True)

        # 5. Update transaction record
        # Append the transaction_id to the end of parameter list for the WHERE clause
        query_params.append(transaction_id)
        
        # Join the list into a clean query string: "SET date = ?, amount = ?"
        sql_script = f"UPDATE transactions SET {', '.join(update_fields)} WHERE id = ?;"

        await conn_w.execute(sql_script, tuple(query_params))

        # 6. Update transaction
        new_record = {
            "transaction_type": transaction_type if transaction_type is not None else old_record["transaction_type"],
            "source_id": source_id if source_id is not None else old_record["source_id"],
            "amount": amount if amount is not None else old_record["amount"]
        }

        await update_source_balance(conn_w, new_record)

        await conn_w.commit()

        logger.info(
            "update_transaction_success | transaction_id=%s,  updated_fields=%s",
            transaction_id,
            update_fields
        )
        
        return {
            "status": "success",
            "transaction_id": transaction_id
        }

    except aiosqlite.Error:
        await conn_w.rollback()
        logger.exception(
            "update_transaction_failed | transaction_id=%s",
            transaction_id
        )
        return {
            "status": "error"
        }

@tool(description="Delete an existing transaction permanently from the database by its ID.")
async def delete_transaction(
    config: RunnableConfig,
    transaction_id: int
) -> dict[str, Any]:
    """
    Args:
        transaction_id: The integer primary key ID of the transaction to be removed.
    """
    try:
        db = get_db(config)
    except RuntimeError:
        return {
            "status": "error",
            "message": "System error"
        }

    logger.info("delete_transaction_called | transaction_id=%s", transaction_id)

    conn_w = db.write_conn

    try:
        await conn_w.execute("BEGIN IMMEDIATE")
        # 1. Get transaction record
        record = await get_old_transaction(conn_w, transaction_id)
        
        if not record:
            await conn_w.rollback()
            logger.warning(
                "delete_transaction_failed | transaction_id=%s not found", 
                transaction_id
            )
            return {
                "status" : "error",
                "message" : "transaction_id not found",
                "transaction_id": transaction_id
            }
        

        # 2. Delete transaction record
        await conn_w.execute("DELETE FROM transactions WHERE id = ?;", (transaction_id,))

        # 3. Reverse source balance
        await update_source_balance(conn_w, record, reverse=True)

        await conn_w.commit()
      
        logger.info("delete_transaction_success | removed transaction_id=%s", transaction_id)

        return {
            "status":"success",
            "transaction_id": transaction_id
        }
    except aiosqlite.Error:
        await conn_w.rollback()
        logger.exception("delete_transaction_failed | transaction_id=%s", transaction_id)
        return {"status": "error"}
    