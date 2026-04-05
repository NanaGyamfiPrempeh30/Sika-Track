"""Database setup and queries — supports PostgreSQL (production) and SQLite (local dev).

How it works:
- If DATABASE_URL environment variable is set → use PostgreSQL (Supabase, Render, etc.)
- If DATABASE_URL is not set → fall back to SQLite at ./data/sika.db (local development)

This lets you develop locally with zero setup (SQLite) while using a real
persistent database in production (PostgreSQL via Supabase free tier).
"""
import os  # Access environment variables and file paths

# ---------------------------------------------------------------------------
# Detect which database to use based on environment
# ---------------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL")  # Set in Render dashboard or .env

if DATABASE_URL:
    # =======================================================================
    # POSTGRESQL MODE (production on Render/Supabase)
    # =======================================================================
    # psycopg2 is the standard Python driver for PostgreSQL.
    # We use psycopg2-binary which bundles the C library (no system deps needed).
    import psycopg2                     # PostgreSQL driver
    import psycopg2.extras              # For RealDictCursor (returns rows as dicts)

    # Supabase and some providers use "postgres://" but psycopg2 requires "postgresql://"
    # This fixes the URL format if needed
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

    def get_connection():
        """Open a connection to the PostgreSQL database."""
        conn = psycopg2.connect(DATABASE_URL)  # Connect using the full URL
        conn.autocommit = False                # We'll commit manually for safety
        return conn

    def init_db():
        """Create tables if they don't exist yet (PostgreSQL version).

        Key differences from SQLite:
        - SERIAL instead of INTEGER PRIMARY KEY AUTOINCREMENT
        - TIMESTAMP WITH TIME ZONE for proper timezone handling
        - NOW() instead of CURRENT_TIMESTAMP (works the same, just PostgreSQL style)
        """
        conn = get_connection()
        cur = conn.cursor()

        # Create users table — stores each Telegram user
        cur.execute("""CREATE TABLE IF NOT EXISTS users (
            chat_id BIGINT PRIMARY KEY,                          -- Telegram chat ID (can be large)
            name TEXT DEFAULT '',                                 -- User's first name from Telegram
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()    -- When they first used the bot
        )""")

        # Create transactions table — stores every sale and expense
        cur.execute("""CREATE TABLE IF NOT EXISTS transactions (
            id SERIAL PRIMARY KEY,                               -- Auto-incrementing ID
            chat_id BIGINT NOT NULL,                             -- Which user owns this
            type TEXT NOT NULL,                                  -- 'sale' or 'expense'
            amount REAL NOT NULL,                                -- Money amount in GHS
            category TEXT DEFAULT 'general',                     -- What it was for
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),   -- When it was recorded
            FOREIGN KEY (chat_id) REFERENCES users(chat_id)      -- Link to users table
        )""")

        conn.commit()  # Save the schema changes
        cur.close()
        conn.close()

    def ensure_user(chat_id, name=""):
        """Add user to DB if they don't exist. Update name if they do.

        Uses PostgreSQL's ON CONFLICT ... DO UPDATE (same as SQLite UPSERT).
        """
        _ensure_initialized()  # Create tables if first call
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (chat_id, name) VALUES (%s, %s) "
            "ON CONFLICT (chat_id) DO UPDATE SET name = %s",
            (chat_id, name, name),  # %s placeholders prevent SQL injection
        )
        conn.commit()
        cur.close()
        conn.close()

    def add_transaction(chat_id, txn_type, amount, category):
        """Record a sale or expense in PostgreSQL."""
        _ensure_initialized()  # Create tables if first call
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO transactions (chat_id, type, amount, category) "
            "VALUES (%s, %s, %s, %s)",
            (chat_id, txn_type, amount, category),  # Parameterized query
        )
        conn.commit()
        cur.close()
        conn.close()

    def get_today(chat_id):
        """Get all of today's transactions for a user (PostgreSQL version).

        Uses CURRENT_DATE which respects the database timezone setting.
        Supabase defaults to UTC — same as SQLite's date('now').
        """
        _ensure_initialized()  # Create tables if first call
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)  # Return dicts
        cur.execute(
            "SELECT type, amount, category FROM transactions "
            "WHERE chat_id = %s AND created_at::date = CURRENT_DATE",
            (chat_id,),
        )
        rows = cur.fetchall()  # Get all matching rows as list of dicts
        cur.close()
        conn.close()
        return rows

    def get_week(chat_id):
        """Get all transactions from the last 7 days for a user (PostgreSQL version)."""
        _ensure_initialized()  # Create tables if first call
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)  # Return dicts
        cur.execute(
            "SELECT type, amount, category FROM transactions "
            "WHERE chat_id = %s AND created_at >= NOW() - INTERVAL '7 days'",
            (chat_id,),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return rows

else:
    # =======================================================================
    # SQLITE MODE (local development — no setup required)
    # =======================================================================
    # This is your original code, unchanged. It runs when DATABASE_URL is not set.
    # SQLite stores everything in a single file: ./data/sika.db
    import sqlite3  # Built-in Python database (no install needed)

    DB_PATH = "./data/sika.db"  # Where the database file lives

    def get_connection():
        """Open a connection to the SQLite database."""
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)  # Create data/ folder if missing
        conn = sqlite3.connect(DB_PATH)  # Connect (creates file if it doesn't exist)
        conn.row_factory = sqlite3.Row   # Return rows as dict-like objects
        return conn

    def init_db():
        """Create tables if they don't exist yet (SQLite version)."""
        conn = get_connection()
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY,               -- Telegram chat ID, unique per user
            name TEXT DEFAULT '',                       -- User's first name from Telegram
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,      -- Unique transaction ID
            chat_id INTEGER NOT NULL,                  -- Which user owns this
            type TEXT NOT NULL,                        -- 'sale' or 'expense'
            amount REAL NOT NULL,                      -- Money amount in GHS
            category TEXT DEFAULT 'general',           -- What it was for
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (chat_id) REFERENCES users(chat_id)
        )""")
        conn.commit()
        conn.close()

    def ensure_user(chat_id, name=""):
        """Add user to DB if they don't exist. Update name if they do."""
        _ensure_initialized()  # Create tables if first call
        conn = get_connection()
        conn.execute(
            "INSERT INTO users (chat_id, name) VALUES (?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET name = ?",
            (chat_id, name, name),
        )
        conn.commit()
        conn.close()

    def add_transaction(chat_id, txn_type, amount, category):
        """Record a sale or expense."""
        _ensure_initialized()  # Create tables if first call
        conn = get_connection()
        conn.execute(
            "INSERT INTO transactions (chat_id, type, amount, category) VALUES (?, ?, ?, ?)",
            (chat_id, txn_type, amount, category),
        )
        conn.commit()
        conn.close()

    def get_today(chat_id):
        """Get all of today's transactions for a user."""
        _ensure_initialized()  # Create tables if first call
        conn = get_connection()
        rows = conn.execute(
            "SELECT type, amount, category FROM transactions "
            "WHERE chat_id = ? AND date(created_at) = date('now')",
            (chat_id,),
        ).fetchall()
        conn.close()
        return rows

    def get_week(chat_id):
        """Get all transactions from the last 7 days for a user."""
        _ensure_initialized()  # Create tables if first call
        conn = get_connection()
        rows = conn.execute(
            "SELECT type, amount, category FROM transactions "
            "WHERE chat_id = ? AND created_at >= datetime('now', '-7 days')",
            (chat_id,),
        ).fetchall()
        conn.close()
        return rows


# ---------------------------------------------------------------------------
# Initialize tables lazily — NOT at import time.
# Why? On Render, the database might not be reachable yet when gunicorn first
# loads the module. If init_db() fails at import time, the entire app crashes
# and gunicorn refuses to boot. Instead, we try on first use.
# ---------------------------------------------------------------------------
_db_initialized = False  # Track whether tables have been created


def _ensure_initialized():
    """Create tables if we haven't already. Called before every DB operation.

    This is safe to call repeatedly — after the first success, it's a no-op.
    If the database is temporarily unreachable, it retries on the next call.
    """
    global _db_initialized
    if not _db_initialized:
        try:
            init_db()
            _db_initialized = True  # Don't try again — tables exist
        except Exception as e:
            # Log the error but don't crash the app — retry next time
            import logging
            logging.getLogger(__name__).warning("init_db failed (will retry): %s", e)
