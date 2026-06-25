import sqlite3
from .config import settings

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(
        f"{settings.DATA_DIR}/expense.db", check_same_thread=False
    )
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript("""
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
            date TEXT NOT NULL,
            amount REAL NOT NULL CHECK (amount > 0),
            transaction_type TEXT NOT NULL CHECK (transaction_type IN ('expense', 'income')),
            note TEXT,
            category_id INTEGER,
            source_id INTEGER,
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
    return conn