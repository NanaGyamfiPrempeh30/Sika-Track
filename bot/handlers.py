"""Connect parser + database + formatter to handle each message.

Routes parsed intents to the correct database operations and formats replies.
Supports: sales, expenses, flexible summaries, undo, full data deletion,
listing recent transactions, removing or editing one by its position in that
list, profit checks, and category spending queries.
"""
from datetime import date, datetime  # date.today() for running totals; datetime for formatting

from bot.parser import parse_message  # Understands what the user typed
from bot.database import (  # DB operations
    ensure_user,                    # Create or update user record
    add_transaction,                # Record a sale or expense
    get_date_range,                 # Flexible date-range queries
    get_last_transaction,           # Fetch most recent entry (used by undo + confirmation)
    get_recent_transactions,        # Fetch N most recent (used by 'list' / 'remove N' / 'edit N')
    get_transaction_by_id,          # Re-fetch a row by id for the confirm step
    get_category_range,             # Category-filtered date range query
    get_period_totals,              # Aggregated SUMs over a date range (running totals + profit)
    update_transaction_amount,      # In-place amount edit (used by edit confirm)
    delete_transaction,             # Remove a single transaction by ID
    delete_all_user_data,           # Wipe all user data for privacy/delete command
    set_pending_action,             # Queue a remove/edit pending the user's "yes" reply
    pop_pending_action,             # Atomically read+delete the pending action
)
from bot.formatter import (  # Pretty output
    format_summary,                 # Daily/weekly/range summary
    format_category_summary,        # Per-category spending breakdown
    format_transaction_list,        # Numbered list of recent transactions
    HELP_TEXT,                      # Full command reference
    START_TEXT,                     # Welcome message
)


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


def _format_datetime(created_at):
    """Format a timestamp as 'Wed, Apr 16 at 2:35 PM' for confirmations.

    Used by sale/expense confirmation messages and the recent-list display.
    Handles SQLite string timestamps and PostgreSQL datetime objects alike.
    """
    if isinstance(created_at, str):  # SQLite stores timestamps as ISO-format strings
        dt = datetime.fromisoformat(created_at)
    else:  # PostgreSQL returns native datetime objects
        dt = created_at
    weekday = dt.strftime("%a")            # 'Wed' — short weekday name
    month = dt.strftime("%b")              # 'Apr' — short month name
    day = dt.day                           # No leading zero
    hour = dt.hour % 12 or 12              # 12-hour clock
    minute = dt.strftime("%M")             # Zero-padded minutes
    ampm = "AM" if dt.hour < 12 else "PM"  # AM/PM tag
    return f"{weekday}, {month} {day} at {hour}:{minute} {ampm}"


def _today_running_total_line(chat_id):
    """Build the 'Today so far' line appended to every sale/expense confirmation.

    Uses get_period_totals so this is a single aggregated SQL query, not a row
    scan — the user emphasized keeping the per-insert hit cheap.
    """
    today = date.today()  # Current day in the DB's timezone (UTC, same as queries elsewhere)
    totals = get_period_totals(chat_id, today, today)  # Single round-trip aggregation
    sales = totals["sales"]              # Total sales today
    expenses = totals["expenses"]        # Total expenses today
    profit = sales - expenses            # Net (may be negative)
    return (
        f"📊 Today so far: Sales GHS {sales:.2f} | "
        f"Expenses GHS {expenses:.2f} | "
        f"Profit GHS {profit:.2f}"  # Negative value will display with leading minus
    )


def _format_profit_reply(period_label, totals):
    """Build the one-line response for the 'profit' command.

    Args:
        period_label: 'Today' / 'Yesterday' / 'This week' / 'This month' (from parser).
        totals: dict from get_period_totals — sales/expenses/count.
    """
    if totals["count"] == 0:  # No transactions in this window
        # Spec gives 'today yet' wording; mirror that for other periods too
        word = period_label.lower()  # 'today', 'yesterday', 'this week', 'this month'
        return f"💰 No transactions {word} yet."
    profit = totals["sales"] - totals["expenses"]  # Net for the window
    if profit < 0:  # Loss state — different emoji and label
        return f"📉 {period_label}'s loss: GHS {abs(profit):.2f}"
    return f"💰 {period_label}'s profit: GHS {profit:.2f}"  # Profit (or zero) state


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
        add_transaction(chat_id, "sale", parsed["amount"], parsed["category"])  # Save
        txn = get_last_transaction(chat_id)  # Re-read for the DB-assigned timestamp
        when = _format_datetime(txn["created_at"])  # 'Wed, Apr 16 at 2:35 PM'
        running = _today_running_total_line(chat_id)  # Today's running totals (post-insert)
        return (
            f"✅ Sale recorded: GHS {parsed['amount']:.2f} — {parsed['category']} "
            f"({when})\n"  # Confirmation line
            f"{running}"  # Running daily total beneath
        )

    # --- Record an expense ---
    if intent == "expense":
        add_transaction(chat_id, "expense", parsed["amount"], parsed["category"])  # Save
        txn = get_last_transaction(chat_id)  # Re-read for the timestamp
        when = _format_datetime(txn["created_at"])  # Format for display
        running = _today_running_total_line(chat_id)  # Today's running totals (post-insert)
        return (
            f"✅ Expense recorded: GHS {parsed['amount']:.2f} — {parsed['category']} "
            f"({when})\n"  # Confirmation line
            f"{running}"  # Running daily total beneath
        )

    # --- Flexible date summary (today, yesterday, week, month, day names, specific dates) ---
    if intent == "summary":
        rows = get_date_range(chat_id, parsed["start"], parsed["end"])  # Query by date range
        return format_summary(rows, parsed["label"])  # Format with date header

    # --- Profit query: one-line bottom line over today/yesterday/week/month ---
    if intent == "profit_query":
        totals = get_period_totals(  # Aggregated SUMs — no row scan
            chat_id, parsed["start"], parsed["end"],
        )
        return _format_profit_reply(parsed["label"], totals)  # Single-line reply

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

    # --- List: show last 10 transactions numbered for selective removal/edit ---
    if intent == "list_transactions":
        rows = get_recent_transactions(chat_id, limit=10)  # Newest first, capped at 10
        if not rows:  # User has nothing recorded yet
            return "No transactions yet. Start by recording a sale or expense!"
        return format_transaction_list(rows, _format_datetime)  # Pretty numbered output

    # --- Remove by number: preview the Nth most-recent transaction for deletion ---
    if intent == "remove_by_number":
        n = parsed["n"]  # 1-based index from the user
        if n < 1 or n > 10:  # Spec requires N to be in 1–10
            return "Invalid number. Send 'list' to see your recent transactions."
        rows = get_recent_transactions(chat_id, limit=10)  # Same source the list shows
        if n > len(rows):  # User picked a slot that has no transaction
            return "Invalid number. Send 'list' to see your recent transactions."
        txn = rows[n - 1]  # Convert 1-based to 0-based index
        # Persist the remove descriptor — "yes" (on any worker) will commit it
        set_pending_action(chat_id, "remove", txn["id"])
        txn_type_label = "Sale" if txn["type"] == "sale" else "Expense"  # Human label
        return (
            f"Delete ✅ {txn_type_label} — GHS {txn['amount']:.2f} "
            f"({txn['category']})? Send 'yes' to confirm."
        )

    # --- Edit amount by number: preview the swap, queue it for "yes" confirmation ---
    if intent == "edit_amount":
        n = parsed["n"]  # 1-based index from the user
        new_amount = parsed["new_amount"]  # Replacement amount
        if n < 1 or n > 10:  # Same range rule as remove
            return "Invalid number. Send 'list' to see your recent transactions."
        rows = get_recent_transactions(chat_id, limit=10)  # Same source the list shows
        if n > len(rows):  # User picked a slot beyond what exists
            return "Invalid number. Send 'list' to see your recent transactions."
        txn = rows[n - 1]  # Convert 1-based to 0-based index
        # Persist the edit descriptor — "yes" (on any worker) will commit it
        set_pending_action(chat_id, "edit", txn["id"], new_amount)
        txn_type_label = "Sale" if txn["type"] == "sale" else "Expense"  # Human label
        return (
            f"Update {txn_type_label} — GHS {txn['amount']:.2f} → "
            f"GHS {new_amount:.2f} ({txn['category']})? Send 'yes' to confirm."
        )

    # --- Confirm: dispatch the pending action queued by "remove N" or "edit N to X" ---
    if intent == "remove_confirm":
        pending = pop_pending_action(chat_id)  # Atomic read+delete, durable across workers
        if pending is None:  # User said 'yes' without staging anything first
            return "Nothing to confirm. Send 'list' to see your recent transactions."
        row = get_transaction_by_id(pending["txn_id"])  # Re-read so we can report details
        if not row:  # Row vanished between preview and confirm (e.g. concurrent undo)
            return "That transaction no longer exists. Send 'list' to see what's left."
        txn_type_label = "Sale" if row["type"] == "sale" else "Expense"  # Human label
        if pending["action"] == "remove":  # Delete branch
            delete_transaction(pending["txn_id"])  # Actually remove it from the DB
            return f"Removed: {txn_type_label} — GHS {row['amount']:.2f} ({row['category']})"
        # action == "edit" — update the amount in place
        update_transaction_amount(pending["txn_id"], pending["new_amount"])  # Persist edit
        return (
            f"Updated: {txn_type_label} — GHS {pending['new_amount']:.2f} "
            f"({row['category']})"  # Show the new amount, original category preserved
        )

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

    # --- Category spending query: per-category totals over a time period ---
    if intent == "category_query":
        rows = get_category_range(  # Filter by category + date range
            chat_id,
            parsed["category"],
            parsed["start"],
            parsed["end"],
        )
        return format_category_summary(rows, parsed["category"], parsed["label"])

    # --- Unknown: nothing matched ---
    return "❓ I didn't understand that. Send 'help' to see what I can do."
