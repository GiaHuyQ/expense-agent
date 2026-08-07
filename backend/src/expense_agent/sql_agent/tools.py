from datetime import datetime
from typing import Any

import aiosqlite
from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from src.expense_agent.db import ExpenseDBResource
from src.expense_agent.logging_config import logger


def get_db(config: RunnableConfig) -> ExpenseDBResource:
    """Retrieve the ExpenseDBResource instance from RunnableConfig."""
    db = config.get("configurable", {}).get("db")

    if not db:
        logger.error("get_db_failed | Database connection missing in RunnableConfig")
        raise RuntimeError("Database connection missing.")

    return db


@tool(description="Execute a read-only SQL query against the expense database.")
async def execute_sql(query: str, config: RunnableConfig) -> dict[str, Any]:
    """Execute a read-only SELECT query and return rows as dictionaries.

    Args:
        query: The SQL query to execute.
        config: RunnableConfig containing the database connection.
    """
    try:
        db = get_db(config)
    except RuntimeError:
        return {"status": "error", "message": "System error"}

    logger.info("execute_sql_called | query=%s", query)
    conn = db.read_conn

    try:
        cursor = await conn.execute(query)
        results = await cursor.fetchall()

        if not results:
            return {"status": "success", "rows": []}

        # Pair column names with row values
        columns = [col[0] for col in cursor.description]
        rows = [dict(zip(columns, row)) for row in results]

        return {"status": "success", "rows": rows}

    except aiosqlite.Error:
        logger.exception("execute_sql_failed | query=%s", query)
        return {"status": "error", "message": "Database query failed"}


@tool(description="Create one or more expense/income categories if they do not exist.")
async def add_category(category_names: list[str], config: RunnableConfig) -> dict[str, Any]:
    """Create new categories in bulk.

    Args:
        category_names: List of category names to create.
        config: RunnableConfig containing the database connection.
    """
    try:
        db = get_db(config)
    except RuntimeError:
        return {"status": "error", "message": "System error"}

    if not category_names:
        logger.warning("add_category_invalid | Empty category list provided")
        return {"status": "error", "message": "No category names provided"}

    logger.info("add_category_called | category_names=%s", category_names)
    conn = db.write_conn

    try:
        results = []
        for category in category_names:
            try:
                await conn.execute(
                    "INSERT OR IGNORE INTO categories (category_name) VALUES (?);",
                    (category,),
                )
                results.append({"category_name": category, "status": "success"})
            except aiosqlite.Error as err:
                logger.warning("add_category_item_failed | category=%s | error=%s", category, err)
                results.append({"category_name": category, "status": "error", "message": str(err)})

        await conn.commit()
        return {"status": "success", "results": results}

    except Exception:
        await conn.rollback()
        logger.exception("add_category_failed | category_names=%s", category_names)
        return {"status": "error", "message": "Failed to add categories"}


@tool(description="Create one or more money sources (wallets/accounts) if they do not exist.")
async def add_money_source(
    config: RunnableConfig,
    sources: list[tuple[str, float]],
) -> dict[str, Any]:
    """Create new money sources with initial balances.

    Args:
        config: RunnableConfig containing the database connection.
        sources: List of (source_name, initial_balance) pairs.
    """
    try:
        db = get_db(config)
    except RuntimeError:
        return {"status": "error", "message": "System error"}

    if not sources:
        logger.warning("add_money_source_invalid | Empty sources list provided")
        return {"status": "error", "message": "No money sources provided"}

    logger.info("add_money_source_called | sources=%s", sources)
    conn = db.write_conn

    try:
        results = []
        for source_name, initial_balance in sources:
            if initial_balance < 0:
                logger.warning(
                    "add_money_source_invalid_balance | source=%s | balance=%s",
                    source_name,
                    initial_balance,
                )
                results.append({
                    "source_name": source_name,
                    "status": "error",
                    "message": "Source balance cannot be negative",
                })
                continue

            try:
                await conn.execute(
                    "INSERT OR IGNORE INTO sources (source_name, balance) VALUES (?, ?);",
                    (source_name, initial_balance),
                )
                results.append({"source_name": source_name, "status": "success"})
            except aiosqlite.Error as err:
                logger.warning("add_money_source_item_failed | source=%s | error=%s", source_name, err)
                results.append({"source_name": source_name, "status": "error", "message": str(err)})

        await conn.commit()
        return {"status": "success", "results": results}

    except aiosqlite.Error:
        await conn.rollback()
        logger.exception("add_money_source_failed | sources=%s", sources)
        return {"status": "error", "message": "Failed to add money sources"}


@tool(description="Add a new expense or income transaction strictly using valid category and source IDs.")
async def add_transaction(
    config: RunnableConfig,
    transaction_date: str,
    amount: int,
    transaction_type: str,
    category_id: int,
    source_id: int,
    note: str,
) -> dict[str, Any]:
    """Record a new transaction and update the money source balance.

    Args:
        config: RunnableConfig containing the database connection.
        transaction_date: Transaction date formatted as 'YYYY-MM-DD'.
        amount: Transaction monetary amount (must be > 0).
        transaction_type: Strictly 'expense' or 'income'.
        category_id: Valid integer ID of the category.
        source_id: Valid integer ID of the money source.
        note: Description or note for the transaction.
    """
    # 1. Input Validation
    if amount <= 0:
        logger.warning("add_transaction_invalid_amount | amount=%s", amount)
        return {"status": "error", "message": "Invalid amount"}

    transaction_type = transaction_type.lower()
    if transaction_type not in {"expense", "income"}:
        logger.warning("add_transaction_invalid_type | transaction_type=%s", transaction_type)
        return {"status": "error", "message": "Invalid transaction type"}

    try:
        datetime.strptime(transaction_date, "%Y-%m-%d")
    except ValueError:
        logger.warning("add_transaction_invalid_date | transaction_date=%s", transaction_date)
        return {"status": "error", "message": "Invalid transaction date format. Expected YYYY-MM-DD"}

    try:
        db = get_db(config)
    except RuntimeError:
        return {"status": "error", "message": "System error"}

    logger.info(
        "add_transaction_called | date=%s | amount=%s | type=%s | category_id=%s | source_id=%s",
        transaction_date,
        amount,
        transaction_type,
        category_id,
        source_id,
    )

    conn_w = db.write_conn

    try:
        # 2. Begin Transaction
        await conn_w.execute("BEGIN IMMEDIATE")

        # Validate Category existence
        cursor = await conn_w.execute("SELECT 1 FROM categories WHERE category_id = ?", (category_id,))
        if await cursor.fetchone() is None:
            await conn_w.rollback()
            logger.warning("add_transaction_failed | category_id=%s not found", category_id)
            return {"status": "error", "message": "Category not found"}

        # Validate Source existence & balance
        cursor = await conn_w.execute("SELECT balance FROM sources WHERE source_id = ?", (source_id,))
        row = await cursor.fetchone()

        if row is None:
            await conn_w.rollback()
            logger.warning("add_transaction_failed | source_id=%s not found", source_id)
            return {"status": "error", "message": "Source not found"}

        current_balance = row[0]

        # Business Logic: Check sufficient funds for expenses
        if transaction_type == "expense":
            if current_balance < amount:
                await conn_w.rollback()
                logger.warning("add_transaction_failed | insufficient balance on source_id=%s", source_id)
                return {"status": "error", "message": "Insufficient balance"}
            new_balance = current_balance - amount
        else:
            new_balance = current_balance + amount

        # Insert Transaction
        cursor = await conn_w.execute(
            """
            INSERT INTO transactions (transaction_date, amount, transaction_type, category_id, source_id, note)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (transaction_date, amount, transaction_type, category_id, source_id, note),
        )
        transaction_id = cursor.lastrowid

        # Update Source Balance
        await conn_w.execute(
            "UPDATE sources SET balance = ? WHERE source_id = ?",
            (new_balance, source_id),
        )

        await conn_w.commit()

        logger.info("add_transaction_success | transaction_id=%s", transaction_id)
        return {"status": "success", "transaction_id": transaction_id}

    except aiosqlite.Error:
        await conn_w.rollback()
        logger.exception("add_transaction_failed | transaction_date=%s", transaction_date)
        return {"status": "error", "message": "Add transaction failed"}


FIELDS = (
    "transaction_date",
    "amount",
    "transaction_type",
    "category_id",
    "source_id",
    "note",
)


async def get_old_transaction(conn: aiosqlite.Connection, transaction_id: int) -> dict[str, Any] | None:
    """Fetch an existing transaction record by ID. Returns None if not found."""
    try:
        cursor = await conn.execute(
            """
            SELECT transaction_date, amount, transaction_type, category_id, source_id, note
            FROM transactions WHERE id = ?
            """,
            (transaction_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None

        return dict(zip(FIELDS, row))

    except aiosqlite.Error:
        logger.exception("get_old_transaction_failed | transaction_id=%s", transaction_id)
        raise


async def update_source_balance(
    conn: aiosqlite.Connection, record: dict[str, Any], reverse: bool = False
) -> None:
    """Apply or reverse the balance impact of a transaction record on a money source.

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
            raise RuntimeError(f"source_id {source_id} not found.")

        current_balance = row[0]

        if reverse:
            new_balance = current_balance + amount if transaction_type == "expense" else current_balance - amount
        else:
            new_balance = current_balance - amount if transaction_type == "expense" else current_balance + amount

        await conn.execute("UPDATE sources SET balance = ? WHERE source_id = ?", (new_balance, source_id))

    except aiosqlite.Error:
        logger.exception("update_source_balance_failed | source_id=%s | reverse=%s", source_id, reverse)
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
    note: str | None = None,
) -> dict[str, Any]:
    """Update specific transaction fields and adjust the affected source balances.

    Args:
        config: RunnableConfig containing the database connection.
        transaction_id: Primary key ID of the transaction to modify.
        transaction_date: Optional new date string ('YYYY-MM-DD').
        amount: Optional new positive monetary value.
        transaction_type: Optional new type ('expense' or 'income').
        category_id: Optional new category ID.
        source_id: Optional new money source ID.
        note: Optional new description text.
    """
    try:
        db = get_db(config)
    except RuntimeError:
        return {"status": "error", "message": "System error"}

    logger.info("update_transaction_called | transaction_id=%s", transaction_id)
    conn_w = db.write_conn

    try:
        await conn_w.execute("BEGIN IMMEDIATE")

        # 1. Fetch existing transaction record inside the write transaction lock
        old_record = await get_old_transaction(conn_w, transaction_id)
        if not old_record:
            await conn_w.rollback()
            logger.warning("update_transaction_failed | transaction_id=%s not found", transaction_id)
            return {
                "status": "error",
                "message": "transaction_id not found",
                "transaction_id": transaction_id,
            }

        # 2. Build update query and validate updated fields
        update_fields = []
        query_params = []

        target_amount = amount if amount is not None else old_record["amount"]
        target_type = transaction_type.lower() if transaction_type is not None else old_record["transaction_type"]

        if amount is not None:
            if amount <= 0:
                await conn_w.rollback()
                logger.warning("update_transaction_invalid_amount | amount=%s", amount)
                return {"status": "error", "message": "Invalid amount"}

            update_fields.append("amount = ?")
            query_params.append(amount)

        if transaction_type is not None:
            if target_type not in {"expense", "income"}:
                await conn_w.rollback()
                logger.warning("update_transaction_invalid_type | transaction_type=%s", transaction_type)
                return {"status": "error", "message": "transaction_type must be 'expense' or 'income'"}

            update_fields.append("transaction_type = ?")
            query_params.append(target_type)

        if transaction_date is not None:
            try:
                datetime.strptime(transaction_date, "%Y-%m-%d")
            except ValueError:
                await conn_w.rollback()
                logger.warning("update_transaction_invalid_date | transaction_date=%s", transaction_date)
                return {"status": "error", "message": "Invalid transaction date format"}

            update_fields.append("transaction_date = ?")
            query_params.append(transaction_date)

        if category_id is not None:
            cursor = await conn_w.execute("SELECT 1 FROM categories WHERE category_id=?", (category_id,))
            if not await cursor.fetchone():
                await conn_w.rollback()
                logger.warning("update_transaction_failed | category_id=%s not found", category_id)
                return {"status": "error", "message": f"category_id: {category_id} not found"}

            update_fields.append("category_id = ?")
            query_params.append(category_id)

        if source_id is not None:
            cursor = await conn_w.execute("SELECT balance FROM sources WHERE source_id=?", (source_id,))
            row = await cursor.fetchone()
            if not row:
                await conn_w.rollback()
                logger.warning("update_transaction_failed | source_id=%s not found", source_id)
                return {"status": "error", "message": f"source_id: {source_id} not found"}

            update_fields.append("source_id = ?")
            query_params.append(source_id)

        if note is not None:
            update_fields.append("note = ?")
            query_params.append(note)

        if not update_fields:
            await conn_w.rollback()
            logger.warning("update_transaction_ignored | no fields provided for id=%s", transaction_id)
            return {"status": "error", "message": "No fields provided for update"}

        # 3. Apply balance modifications
        # Reverse old transaction impact on source balance
        await update_source_balance(conn_w, old_record, reverse=True)

        # Apply database update
        query_params.append(transaction_id)
        sql_script = f"UPDATE transactions SET {', '.join(update_fields)} WHERE id = ?;"
        await conn_w.execute(sql_script, tuple(query_params))

        # Apply new transaction impact on source balance
        new_record = {
            "transaction_type": target_type,
            "source_id": source_id if source_id is not None else old_record["source_id"],
            "amount": target_amount,
        }
        await update_source_balance(conn_w, new_record, reverse=False)

        await conn_w.commit()

        logger.info(
            "update_transaction_success | transaction_id=%s | updated_fields=%s",
            transaction_id,
            update_fields,
        )
        return {"status": "success", "message": f"Successfully updated transaction_id: {transaction_id}"}

    except aiosqlite.Error:
        await conn_w.rollback()
        logger.exception("update_transaction_failed | transaction_id=%s", transaction_id)
        return {"status": "error", "message": "Update transaction failed"}


@tool(description="Delete an existing transaction permanently from the database by its ID.")
async def delete_transaction(config: RunnableConfig, transaction_id: int) -> dict[str, Any]:
    """Delete a transaction and restore the original source balance.

    Args:
        config: RunnableConfig containing the database connection.
        transaction_id: Primary key ID of the transaction to delete.
    """
    try:
        db = get_db(config)
    except RuntimeError:
        return {"status": "error", "message": "System error"}

    logger.info("delete_transaction_called | transaction_id=%s", transaction_id)
    conn_w = db.write_conn

    try:
        await conn_w.execute("BEGIN IMMEDIATE")

        # 1. Retrieve transaction record
        record = await get_old_transaction(conn_w, transaction_id)
        if not record:
            await conn_w.rollback()
            logger.warning("delete_transaction_failed | transaction_id=%s not found", transaction_id)
            return {
                "status": "error",
                "message": "transaction_id not found",
                "transaction_id": transaction_id,
            }

        # 2. Delete transaction row
        await conn_w.execute("DELETE FROM transactions WHERE id = ?;", (transaction_id,))

        # 3. Reverse source balance impact
        await update_source_balance(conn_w, record, reverse=True)

        await conn_w.commit()

        logger.info("delete_transaction_success | removed transaction_id=%s", transaction_id)
        return {"status": "success", "transaction_id": transaction_id}

    except aiosqlite.Error:
        await conn_w.rollback()
        logger.exception("delete_transaction_failed | transaction_id=%s", transaction_id)
        return {"status": "error", "message": "Delete transaction failed"}


@tool(description="Transfer money between two money sources.")
async def transfer_money(
    fromSource_id: int,
    toSource_id: int,
    amount: int,
    transfer_date: str,
    config: RunnableConfig,
) -> dict[str, Any]:
    """Transfer funds directly from one source wallet to another.

    Args:
        fromSource_id: Origin wallet integer ID.
        toSource_id: Destination wallet integer ID.
        amount: Positive monetary value to transfer.
        transfer_date: Date string formatted as 'YYYY-MM-DD'.
        config: RunnableConfig containing the database connection.
    """
    if amount <= 0:
        logger.warning("transfer_money_invalid_amount | amount=%s", amount)
        return {"status": "error", "message": "Invalid amount"}

    if fromSource_id == toSource_id:
        logger.warning("transfer_money_same_source | source_id=%s", fromSource_id)
        return {"status": "error", "message": "Source and destination wallets must be different"}

    if transfer_date:
        try:
            datetime.strptime(transfer_date, "%Y-%m-%d")
        except ValueError:
            logger.warning("transfer_money_invalid_date | transfer_date=%s", transfer_date)
            return {"status": "error", "message": "Invalid transfer date format."}

    try:
        db = get_db(config)
    except RuntimeError:
        return {"status": "error", "message": "System error"}

    logger.info(
        "transfer_money_called | fromSource_id=%s | toSource_id=%s | amount=%s",
        fromSource_id,
        toSource_id,
        amount,
    )

    conn_w = db.write_conn

    try:
        await conn_w.execute("BEGIN IMMEDIATE")

        # 1. Validate source wallet
        cursor = await conn_w.execute(
            "SELECT source_name, balance FROM sources WHERE source_id = ?", (fromSource_id,)
        )
        row = await cursor.fetchone()

        if not row:
            await conn_w.rollback()
            logger.warning("transfer_money_failed | fromSource_id=%s not found", fromSource_id)
            return {"status": "error", "message": "fromSource_id not found"}

        from_source_name, from_source_balance = row[0], row[1]
        if from_source_balance < amount:
            await conn_w.rollback()
            logger.warning("transfer_money_failed | insufficient balance on fromSource_id=%s", fromSource_id)
            return {"status": "error", "message": "Insufficient fromSource balance"}

        # 2. Validate destination wallet
        cursor = await conn_w.execute(
            "SELECT source_name, balance FROM sources WHERE source_id = ?", (toSource_id,)
        )
        row = await cursor.fetchone()

        if not row:
            await conn_w.rollback()
            logger.warning("transfer_money_failed | toSource_id=%s not found", toSource_id)
            return {"status": "error", "message": "toSource_id not found"}

        to_source_name, to_source_balance = row[0], row[1]

        # 3. Create double-entry transaction records
        # Deduct expense from source
        await conn_w.execute(
            """
            INSERT INTO transactions (transaction_date, amount, transaction_type, category_id, source_id, note)
            VALUES (?, ?, 'expense', 1, ?, ?)
            """,
            (transfer_date, amount, fromSource_id, f"Transferred {amount} to {to_source_name}"),
        )
        await conn_w.execute(
            "UPDATE sources SET balance = ? WHERE source_id = ?",
            (from_source_balance - amount, fromSource_id),
        )

        # Add income to destination
        await conn_w.execute(
            """
            INSERT INTO transactions (transaction_date, amount, transaction_type, category_id, source_id, note)
            VALUES (?, ?, 'income', 1, ?, ?)
            """,
            (transfer_date, amount, toSource_id, f"Received {amount} from {from_source_name}"),
        )
        await conn_w.execute(
            "UPDATE sources SET balance = ? WHERE source_id = ?",
            (to_source_balance + amount, toSource_id),
        )

        await conn_w.commit()

        logger.info(
            "transfer_money_success | fromSource_id=%s | toSource_id=%s | amount=%s",
            fromSource_id,
            toSource_id,
            amount,
        )

        return {
            "status": "success",
            "message": f"Successfully transferred {amount} from {from_source_name} to {to_source_name}",
        }

    except aiosqlite.Error:
        await conn_w.rollback()
        logger.exception(
            "transfer_money_failed | fromSource_id=%s | toSource_id=%s | amount=%s",
            fromSource_id,
            toSource_id,
            amount,
        )
        return {"status": "error", "message": "Transfer money cross sources failed"}