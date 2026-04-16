"""Connect parser + database + formatter to handle each message.

Routes parsed intents to the correct database operations and formats replies.
Supports: sales, expenses, flexible summaries, undo, and full data deletion.
"""
from datetime import datetime  # For formatting transaction timestamps

from bot.parser import parse_message  # Understands what the user typed
from bot.database import (  # DB operations
    ensure_user,             # Create or update user record
    add_transaction,         # Record a sale or expense
    get_date_range,          # Flexible date-range queries (new — replaces get_today/get_week)
    get_last_transaction,    # Fetch most recent entry for undo preview (new)
    delete_transaction,      # Remove a single transaction by ID (new)
    delete_all_user_data,    # Wipe all user data for privacy/delete command (new)
)
from bot.formatter import format_summary, HELP_TEXT, START_TEXT  # Pretty output


def _format_time(created_at):
    """Format a transaction timestamp as '2:35 PM' for the undo preview.

    Handles both string (SQLite returns ISO strings) and datetime
    (PostgreSQL returns datetime objects) inputs.
    """
    if isinstance(created_at, str):  # SQLite stores timestamps as ISO-format strings
        dt = datetime.fromisoformat(created_at)
    else:  # PostgreSQL returns native datetime objects
        dt = created_at
    hour = dt.hour % 12 or 12  # Convert 24h → 12h (0→12, 13→1, etc.)
    minute = dt.strftime("%M")  # Zero-padded minutes
    ampm = "AM" if dt.hour < 12 else "PM"  # Morning or afternoon
    return f"{hour}:{minute} {ampm}"


def handle_message(chat_id, first_name, text):
    """Process one message and return a reply string.

    Args:
        chat_id: Telegram chat ID (unique per user)
        first_name: User's Telegram first name (for DB storage)
        text: The raw message text they sent
    """
    ensure_user(chat_id, first_name)  # Create or update user in DB with their name
    parsed = parse_message(text)  # Parse the message into a structured intent
    intent = parsed["intent"]

    # --- Welcome message with privacy notice (triggered by /start) ---
    if intent == "start":
        return START_TEXT  # Welcome + privacy info + pointer to help

    # --- Full command reference (triggered by /help or "help") ---
    if intent == "help":
        return HELP_TEXT  # All available commands with examples

    # --- Record a sale ---
    if intent == "sale":
        add_transaction(chat_id, "sale", parsed["amount"], parsed["category"])  # Save to DB
        return f"✅ Sale recorded: GHS {parsed['amount']:.2f} — {parsed['category']}"  # Confirm

    # --- Record an expense ---
    if intent == "expense":
        add_transaction(chat_id, "expense", parsed["amount"], parsed["category"])  # Save to DB
        return f"✅ Expense recorded: GHS {parsed['amount']:.2f} — {parsed['category']}"  # Confirm

    # --- Flexible date summary (today, yesterday, week, month, day names, specific dates) ---
    if intent == "summary":
        rows = get_date_range(chat_id, parsed["start"], parsed["end"])  # Query by date range
        return format_summary(rows, parsed["label"])  # Format with date header

    # --- Undo: preview the last transaction before deleting ---
    if intent == "undo":
        txn = get_last_transaction(chat_id)  # Fetch most recent transaction
        if not txn:  # No transactions exist for this user
            return "Nothing to undo — you have no recorded transactions."
        txn_type = "Sale" if txn["type"] == "sale" else "Expense"  # Human-readable type
        time_str = _format_time(txn["created_at"])  # Format timestamp as "2:35 PM"
        return (
            f"Last entry: ✅ {txn_type} — GHS {txn['amount']:.2f} "
            f"({txn['category']}) at {time_str}.\n"
            f"Send 'yes undo' to remove it."
        )

    # --- Confirm undo: actually delete the last transaction ---
    if intent == "undo_confirm":
        txn = get_last_transaction(chat_id)  # Re-fetch to get current last entry
        if not txn:  # Edge case: no transactions left
            return "Nothing to undo — you have no recorded transactions."
        delete_transaction(txn["id"])  # Remove the single transaction from DB
        txn_type = "Sale" if txn["type"] == "sale" else "Expense"
        return f"Removed: {txn_type} — GHS {txn['amount']:.2f} ({txn['category']})"

    # --- Delete: ask for confirmation before wiping all data ---
    if intent == "delete":
        return (
            "⚠️ Are you sure? This will permanently delete all your records.\n"
            "Reply 'yes delete' to confirm."
        )

    # --- Confirm delete: wipe all user data (transactions + user record) ---
    if intent == "delete_confirm":
        delete_all_user_data(chat_id)  # Remove everything for this chat_id
        return "All your data has been deleted. Send any message to start fresh."

    # --- Unknown: nothing matched ---
    return "❓ I didn't understand that. Send 'help' to see what I can do."
