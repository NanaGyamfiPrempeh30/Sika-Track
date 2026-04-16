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

    def get_date_range(chat_id, start_date, end_date):
        """Get transactions between start_date and end_date inclusive (PostgreSQL).

        Used by all summary commands (today, yesterday, week, month, specific dates).
        Casts created_at to date for clean day-boundary comparisons.

        Args:
            chat_id: user's Telegram chat ID
            start_date: datetime.date — start of range (inclusive)
            end_date: datetime.date — end of range (inclusive)
        """
        _ensure_initialized()  # Create tables if first call
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)  # Return dicts
        cur.execute(
            "SELECT type, amount, category FROM transactions "
            "WHERE chat_id = %s AND created_at::date >= %s AND created_at::date <= %s",
            (chat_id, start_date, end_date),  # psycopg2 handles date objects natively
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return rows

    def get_last_transaction(chat_id):
        """Get the most recent transaction for a user, or None (PostgreSQL).

        Returns dict with: id, type, amount, category, created_at.
        Used by the undo command to preview and then delete the last entry.
        Orders by created_at DESC, id DESC to break ties deterministically.
        """
        _ensure_initialized()  # Create tables if first call
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)  # Return dict
        cur.execute(
            "SELECT id, type, amount, category, created_at FROM transactions "
            "WHERE chat_id = %s ORDER BY created_at DESC, id DESC LIMIT 1",
            (chat_id,),  # Only this user's transactions
        )
        row = cur.fetchone()  # Single row or None if no transactions
        cur.close()
        conn.close()
        return row

    def delete_transaction(txn_id):
        """Delete a single transaction by its ID (PostgreSQL).

        Used by the undo confirmation to remove only the last entry.
        """
        _ensure_initialized()  # Create tables if first call
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM transactions WHERE id = %s", (txn_id,))
        conn.commit()  # Persist the deletion
        cur.close()
        conn.close()

    def delete_all_user_data(chat_id):
        """Delete all transactions and user record for a chat_id (PostgreSQL).

        Called when user confirms 'yes delete' to erase everything.
        Transactions are deleted first (foreign key constraint requires this),
        then the user record itself is removed.
        """
        _ensure_initialized()  # Create tables if first call
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM transactions WHERE chat_id = %s", (chat_id,))  # Txns first
        cur.execute("DELETE FROM users WHERE chat_id = %s", (chat_id,))  # Then user record
        conn.commit()  # Persist both deletions in one transaction
        cur.close()
        conn.close()

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

    def get_date_range(chat_id, start_date, end_date):
        """Get transactions between start_date and end_date inclusive (SQLite).

        Used by all summary commands. Converts date objects to ISO strings
        for comparison with SQLite's date() function.

        Args:
            chat_id: user's Telegram chat ID
            start_date: datetime.date — start of range (inclusive)
            end_date: datetime.date — end of range (inclusive)
        """
        _ensure_initialized()  # Create tables if first call
        conn = get_connection()
        rows = conn.execute(
            "SELECT type, amount, category FROM transactions "
            "WHERE chat_id = ? AND date(created_at) >= ? AND date(created_at) <= ?",
            (chat_id, start_date.isoformat(), end_date.isoformat()),  # date → "YYYY-MM-DD"
        ).fetchall()
        conn.close()
        return rows

    def get_last_transaction(chat_id):
        """Get the most recent transaction for a user, or None (SQLite).

        Returns dict-like sqlite3.Row with: id, type, amount, category, created_at.
        Used by the undo command to preview and delete the last entry.
        """
        _ensure_initialized()  # Create tables if first call
        conn = get_connection()
        row = conn.execute(
            "SELECT id, type, amount, category, created_at FROM transactions "
            "WHERE chat_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
            (chat_id,),  # Only this user's transactions
        ).fetchone()  # Single row or None
        conn.close()
        return row

    def delete_transaction(txn_id):
        """Delete a single transaction by its ID (SQLite).

        Used by the undo confirmation to remove only the last entry.
        """
        _ensure_initialized()  # Create tables if first call
        conn = get_connection()
        conn.execute("DELETE FROM transactions WHERE id = ?", (txn_id,))
        conn.commit()  # Persist the deletion
        conn.close()

    def delete_all_user_data(chat_id):
        """Delete all transactions and user record for a chat_id (SQLite).

        Called when user confirms 'yes delete' to erase everything.
        Transactions deleted first (foreign key), then user record.
        """
        _ensure_initialized()  # Create tables if first call
        conn = get_connection()
        conn.execute("DELETE FROM transactions WHERE chat_id = ?", (chat_id,))  # Txns first
        conn.execute("DELETE FROM users WHERE chat_id = ?", (chat_id,))  # Then user record
        conn.commit()  # Persist both deletions
        conn.close()


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
