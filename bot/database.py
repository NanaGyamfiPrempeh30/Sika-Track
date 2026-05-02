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

        # Create pending_actions table — persists "remove N" / "edit N to X" between
        # the preview message and the user's "yes" reply. Stored in the DB (not
        # process memory) so multiple gunicorn workers can share the state — any
        # worker that handles "yes" can find the pending row.
        cur.execute("""CREATE TABLE IF NOT EXISTS pending_actions (
            chat_id BIGINT PRIMARY KEY,                          -- One pending action per user
            action TEXT NOT NULL,                                -- 'remove' or 'edit'
            txn_id INTEGER NOT NULL,                             -- Which transaction
            new_amount REAL,                                     -- For 'edit' only; NULL for 'remove'
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()    -- When the preview was shown
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

    def get_transaction_by_id(txn_id):
        """Look up a single transaction row by its primary key (PostgreSQL).

        Used by the targeted-delete confirm step to retrieve the row we
        previewed earlier so we can report its details after deletion.
        """
        _ensure_initialized()  # Create tables if first call
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT id, type, amount, category, created_at FROM transactions WHERE id = %s",
            (txn_id,),  # Single-row primary-key lookup
        )
        row = cur.fetchone()  # None if the row was already deleted
        cur.close()
        conn.close()
        return row

    def get_recent_transactions(chat_id, limit=10):
        """Get the N most recent transactions for a user (PostgreSQL).

        Used by the 'list' command to show a numbered preview, and by
        'remove N' to look up which transaction the user pointed at.
        Order: newest first, with id as a tiebreaker for deterministic numbering.
        """
        _ensure_initialized()  # Create tables if first call
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)  # Return dicts
        cur.execute(
            "SELECT id, type, amount, category, created_at FROM transactions "
            "WHERE chat_id = %s ORDER BY created_at DESC, id DESC LIMIT %s",
            (chat_id, limit),  # Cap at limit rows
        )
        rows = cur.fetchall()  # List of recent rows, newest first
        cur.close()
        conn.close()
        return rows

    def get_category_range(chat_id, category, start_date, end_date):
        """Get transactions for a specific category in a date range (PostgreSQL).

        Used by category spending queries ("food this month", "kenkey this week").
        Category match is case-insensitive — defensive even though parser lowercases.

        Args:
            chat_id: user's Telegram chat ID
            category: category name to filter on (e.g. "food")
            start_date: datetime.date — start of range (inclusive)
            end_date: datetime.date — end of range (inclusive)
        """
        _ensure_initialized()  # Create tables if first call
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)  # Return dicts
        cur.execute(
            "SELECT type, amount, category FROM transactions "
            "WHERE chat_id = %s AND LOWER(category) = LOWER(%s) "
            "AND created_at::date >= %s AND created_at::date <= %s",
            (chat_id, category, start_date, end_date),  # Filter by user/category/date
        )
        rows = cur.fetchall()  # All matching rows for aggregation
        cur.close()
        conn.close()
        return rows

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

    def update_transaction_amount(txn_id, new_amount):
        """Update the amount on a single transaction (PostgreSQL).

        Used by the 'edit N to AMOUNT' flow. Type, category and timestamp
        are preserved — only the amount changes.
        """
        _ensure_initialized()  # Create tables if first call
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE transactions SET amount = %s WHERE id = %s",
            (new_amount, txn_id),  # Parameterized to prevent injection
        )
        conn.commit()  # Persist the change
        cur.close()
        conn.close()

    def get_period_totals(chat_id, start_date, end_date):
        """Sum sales and expenses over a date range in one round trip (PostgreSQL).

        Returns dict {sales: float, expenses: float, count: int}. Done with
        SQL aggregation rather than fetching rows so the per-insert running
        total stays cheap even with lots of transactions.
        """
        _ensure_initialized()  # Create tables if first call
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT "
            "COALESCE(SUM(CASE WHEN type = 'sale' THEN amount ELSE 0 END), 0), "      # Sales sum
            "COALESCE(SUM(CASE WHEN type = 'expense' THEN amount ELSE 0 END), 0), "    # Expense sum
            "COUNT(*) "                                                                # Total rows
            "FROM transactions "
            "WHERE chat_id = %s AND created_at::date >= %s AND created_at::date <= %s",
            (chat_id, start_date, end_date),  # Bounded date window
        )
        sales_sum, expense_sum, total_count = cur.fetchone()  # Single aggregated row
        cur.close()
        conn.close()
        # Cast to float — psycopg2 may return Decimal; the bot uses floats elsewhere
        return {
            "sales": float(sales_sum),
            "expenses": float(expense_sum),
            "count": int(total_count),
        }

    def delete_all_user_data(chat_id):
        """Delete all transactions, pending actions, and user record (PostgreSQL).

        Called when user confirms 'yes delete' to erase everything.
        Order: pending_actions and transactions first (no FK to users yet but
        keeps semantics consistent), then the user record.
        """
        _ensure_initialized()  # Create tables if first call
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM pending_actions WHERE chat_id = %s", (chat_id,))  # Drop pending
        cur.execute("DELETE FROM transactions WHERE chat_id = %s", (chat_id,))  # Txns next
        cur.execute("DELETE FROM users WHERE chat_id = %s", (chat_id,))  # Then user record
        conn.commit()  # Persist all three deletions atomically
        cur.close()
        conn.close()

    def set_pending_action(chat_id, action, txn_id, new_amount=None):
        """Persist a pending 'remove' or 'edit' for this chat (PostgreSQL).

        Replaces any prior pending row — only one action queued at a time per
        user, mirroring the dict-overwrite semantics the in-memory version had.
        """
        _ensure_initialized()  # Create tables if first call
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO pending_actions (chat_id, action, txn_id, new_amount) "
            "VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (chat_id) DO UPDATE SET "
            "action = EXCLUDED.action, "                  # Replace action ('remove' ↔ 'edit')
            "txn_id = EXCLUDED.txn_id, "                  # Point at the new transaction
            "new_amount = EXCLUDED.new_amount, "          # NULL for remove, value for edit
            "created_at = NOW()",                          # Refresh timestamp on overwrite
            (chat_id, action, txn_id, new_amount),
        )
        conn.commit()  # Persist the queued action
        cur.close()
        conn.close()

    def pop_pending_action(chat_id):
        """Atomically read+delete the pending action for a chat (PostgreSQL).

        Returns dict with action/txn_id/new_amount, or None if nothing pending.
        DELETE...RETURNING guarantees a single round-trip and that two workers
        racing on the same 'yes' can't both see the row.
        """
        _ensure_initialized()  # Create tables if first call
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)  # Return dict
        cur.execute(
            "DELETE FROM pending_actions WHERE chat_id = %s "
            "RETURNING action, txn_id, new_amount",
            (chat_id,),
        )
        row = cur.fetchone()  # None if no row was deleted
        conn.commit()  # Persist the deletion
        cur.close()
        conn.close()
        return row

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
        # Pending actions for the "remove N" / "edit N to X" → "yes" flow.
        # Persisted so we don't depend on process memory (unused locally,
        # required in production where multiple gunicorn workers exist).
        conn.execute("""CREATE TABLE IF NOT EXISTS pending_actions (
            chat_id INTEGER PRIMARY KEY,               -- One pending action per user
            action TEXT NOT NULL,                      -- 'remove' or 'edit'
            txn_id INTEGER NOT NULL,                   -- Which transaction
            new_amount REAL,                           -- For 'edit' only; NULL for 'remove'
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

    def get_transaction_by_id(txn_id):
        """Look up a single transaction row by its primary key (SQLite).

        Used by the targeted-delete confirm step to retrieve the row we
        previewed earlier so we can report its details after deletion.
        """
        _ensure_initialized()  # Create tables if first call
        conn = get_connection()
        row = conn.execute(
            "SELECT id, type, amount, category, created_at FROM transactions WHERE id = ?",
            (txn_id,),  # Single-row primary-key lookup
        ).fetchone()  # None if already deleted
        conn.close()
        return row

    def get_recent_transactions(chat_id, limit=10):
        """Get the N most recent transactions for a user (SQLite).

        Used by the 'list' command to show a numbered preview, and by
        'remove N' to look up which transaction the user pointed at.
        Order: newest first, with id as a tiebreaker for deterministic numbering.
        """
        _ensure_initialized()  # Create tables if first call
        conn = get_connection()
        rows = conn.execute(
            "SELECT id, type, amount, category, created_at FROM transactions "
            "WHERE chat_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (chat_id, limit),  # Cap at limit rows
        ).fetchall()
        conn.close()
        return rows

    def get_category_range(chat_id, category, start_date, end_date):
        """Get transactions for a specific category in a date range (SQLite).

        Used by category spending queries ("food this month", "kenkey this week").
        Category match is case-insensitive via LOWER() comparison.

        Args:
            chat_id: user's Telegram chat ID
            category: category name (e.g. "food")
            start_date: datetime.date — start of range (inclusive)
            end_date: datetime.date — end of range (inclusive)
        """
        _ensure_initialized()  # Create tables if first call
        conn = get_connection()
        rows = conn.execute(
            "SELECT type, amount, category FROM transactions "
            "WHERE chat_id = ? AND LOWER(category) = LOWER(?) "
            "AND date(created_at) >= ? AND date(created_at) <= ?",
            (chat_id, category, start_date.isoformat(), end_date.isoformat()),  # Filter
        ).fetchall()
        conn.close()
        return rows

    def delete_transaction(txn_id):
        """Delete a single transaction by its ID (SQLite).

        Used by the undo confirmation to remove only the last entry.
        """
        _ensure_initialized()  # Create tables if first call
        conn = get_connection()
        conn.execute("DELETE FROM transactions WHERE id = ?", (txn_id,))
        conn.commit()  # Persist the deletion
        conn.close()

    def update_transaction_amount(txn_id, new_amount):
        """Update the amount on a single transaction (SQLite).

        Used by the 'edit N to AMOUNT' flow. Type, category and timestamp
        are preserved — only the amount changes.
        """
        _ensure_initialized()  # Create tables if first call
        conn = get_connection()
        conn.execute(
            "UPDATE transactions SET amount = ? WHERE id = ?",
            (new_amount, txn_id),  # Parameterized to prevent injection
        )
        conn.commit()  # Persist the change
        conn.close()

    def get_period_totals(chat_id, start_date, end_date):
        """Sum sales and expenses over a date range in one round trip (SQLite).

        Returns dict {sales: float, expenses: float, count: int}. Done with
        SQL aggregation rather than fetching rows so the per-insert running
        total stays cheap even with lots of transactions.
        """
        _ensure_initialized()  # Create tables if first call
        conn = get_connection()
        row = conn.execute(
            "SELECT "
            "COALESCE(SUM(CASE WHEN type = 'sale' THEN amount ELSE 0 END), 0), "      # Sales sum
            "COALESCE(SUM(CASE WHEN type = 'expense' THEN amount ELSE 0 END), 0), "    # Expense sum
            "COUNT(*) "                                                                # Total rows
            "FROM transactions "
            "WHERE chat_id = ? AND date(created_at) >= ? AND date(created_at) <= ?",
            (chat_id, start_date.isoformat(), end_date.isoformat()),  # Bounded window
        ).fetchone()
        conn.close()
        # SQLite returns native Python numbers; tuple-index since this is plain Row
        return {
            "sales": float(row[0]),
            "expenses": float(row[1]),
            "count": int(row[2]),
        }

    def delete_all_user_data(chat_id):
        """Delete all transactions, pending actions, and user record (SQLite).

        Called when user confirms 'yes delete' to erase everything.
        """
        _ensure_initialized()  # Create tables if first call
        conn = get_connection()
        conn.execute("DELETE FROM pending_actions WHERE chat_id = ?", (chat_id,))  # Drop pending
        conn.execute("DELETE FROM transactions WHERE chat_id = ?", (chat_id,))  # Txns next
        conn.execute("DELETE FROM users WHERE chat_id = ?", (chat_id,))  # Then user record
        conn.commit()  # Persist all three deletions
        conn.close()

    def set_pending_action(chat_id, action, txn_id, new_amount=None):
        """Persist a pending 'remove' or 'edit' for this chat (SQLite).

        UPSERT replaces any prior pending row — one queued action per user.
        """
        _ensure_initialized()  # Create tables if first call
        conn = get_connection()
        conn.execute(
            "INSERT INTO pending_actions (chat_id, action, txn_id, new_amount) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET "
            "action = excluded.action, "                  # Replace action
            "txn_id = excluded.txn_id, "                  # Point at the new txn
            "new_amount = excluded.new_amount, "          # NULL for remove, value for edit
            "created_at = CURRENT_TIMESTAMP",              # Refresh timestamp
            (chat_id, action, txn_id, new_amount),
        )
        conn.commit()  # Persist the queued action
        conn.close()

    def pop_pending_action(chat_id):
        """Read and delete the pending action for a chat (SQLite).

        Returns sqlite3.Row with action/txn_id/new_amount, or None.
        Done in one connection so the read+delete share an implicit
        transaction — guards against losing a pending row mid-flight.
        """
        _ensure_initialized()  # Create tables if first call
        conn = get_connection()
        row = conn.execute(
            "SELECT action, txn_id, new_amount FROM pending_actions "
            "WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()  # None if nothing pending
        if row is not None:  # Only delete if we actually found something
            conn.execute("DELETE FROM pending_actions WHERE chat_id = ?", (chat_id,))
            conn.commit()  # Persist the deletion
        conn.close()
        return row


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
