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
            CREATE TABLE IF NOT EXISTS categories (
                category_id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_name TEXT NOT NULL UNIQUE
            );

            INSERT OR IGNORE INTO categories (category_name) VALUES ('Transfer');

            CREATE TABLE IF NOT EXISTS sources (
                source_id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_name TEXT NOT NULL UNIQUE,
                balance INTEGER NOT NULL DEFAULT 0 
                    CHECK(balance >= 0)
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_date TEXT NOT NULL,
                amount INTEGER NOT NULL 
                    CHECK(amount > 0),
                transaction_type TEXT NOT NULL
                    CHECK(transaction_type IN ('expense', 'income')),
                category_id INTEGER NOT NULL,
                source_id INTEGER NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(category_id) REFERENCES categories(category_id),
                FOREIGN KEY(source_id) REFERENCES sources(source_id)
            );
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


