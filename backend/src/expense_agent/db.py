from dataclasses import dataclass
import aiosqlite
from .config import settings

@dataclass(slots=True)
class ExpenseDBResource:
    write_conn: aiosqlite.Connection
    read_conn: aiosqlite.Connection

async def create_database() -> ExpenseDBResource:
    """Create and initialize the application database."""
    w_conn: aiosqlite.Connection | None = None
    r_conn: aiosqlite.Connection | None = None

    try:
        w_conn = await aiosqlite.connect(
            f"{settings.DATA_DIR}/expense.db"
        )

        w_conn.row_factory = aiosqlite.Row

        # Configure SQLite
        await w_conn.execute("PRAGMA journal_mode=WAL;")
        await w_conn.execute("PRAGMA foreign_keys=ON;")

        # Create database schema
        await w_conn.executescript("""
            CREATE TABLE IF NOT EXISTS category (
                category_id INTEGER PRIMARY KEY,
                category_name TEXT NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS source (
                source_id INTEGER PRIMARY KEY,
                source_name TEXT NOT NULL UNIQUE,
                initial_balance REAL NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY,
                transaction_date TEXT NOT NULL,
                amount REAL NOT NULL CHECK (amount > 0),
                transaction_type TEXT NOT NULL CHECK (transaction_type IN ('expense', 'income')),
                category_id INTEGER,
                source_id INTEGER,
                note TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, 
                                                     
                CONSTRAINT fk_category FOREIGN KEY (category_id) REFERENCES category(category_id),
                CONSTRAINT fk_source FOREIGN KEY (source_id) REFERENCES source(source_id)
            );

            CREATE VIEW IF NOT EXISTS source_balance AS
            SELECT
                s.source_id,
                s.source_name,
                s.initial_balance
                + COALESCE(SUM(CASE WHEN t.transaction_type = 'income' THEN t.amount ELSE 0 END), 0)
                - COALESCE(SUM(CASE WHEN t.transaction_type = 'expense' THEN t.amount ELSE 0 END), 0)
                    AS current_balance
            FROM source s
            LEFT JOIN transactions t ON t.source_id = s.source_id
            GROUP BY s.source_id;
        """)

        await w_conn.commit()

        r_conn = await aiosqlite.connect(
            f"file:{settings.DATA_DIR}/expense.db?mode=ro",
            uri=True,
        )

        r_conn.row_factory = aiosqlite.Row

        return ExpenseDBResource(
            write_conn=w_conn,
            read_conn=r_conn
        )
    
    except Exception:
        if r_conn is not None:
            await r_conn.close()

        if w_conn is not None:
            await w_conn.close()
        raise