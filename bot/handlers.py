"""Connect parser + database + formatter to handle each message."""
from bot.parser import parse_message  # Understands what the user typed
from bot.database import ensure_user, add_transaction, get_today, get_week  # DB operations
from bot.formatter import format_summary, HELP_TEXT  # Pretty output


def handle_message(chat_id, first_name, text):
    """Process one message and return a reply string.

    Args:
        chat_id: Telegram chat ID (unique per user)
        first_name: User's Telegram first name (for DB storage)
        text: The raw message text they sent
    """
    ensure_user(chat_id, first_name)  # Create or update user in DB with their name
    parsed = parse_message(text)  # Parse the message into an intent
    intent = parsed["intent"]  # What does the user want?

    if intent == "help":  # They need instructions
        return HELP_TEXT  # Send the help/welcome message

    if intent == "sale":  # They made a sale
        add_transaction(chat_id, "sale", parsed["amount"], parsed["category"])  # Save it
        return f"✅ Sale recorded: GHS {parsed['amount']:.2f} — {parsed['category']}"  # Confirm

    if intent == "expense":  # They spent money
        add_transaction(chat_id, "expense", parsed["amount"], parsed["category"])  # Save it
        return f"✅ Expense recorded: GHS {parsed['amount']:.2f} — {parsed['category']}"  # Confirm

    if intent == "summary_today":  # They want today's summary
        rows = get_today(chat_id)  # Fetch today's transactions
        return format_summary(rows, "Today")  # Format and return

    if intent == "summary_week":  # They want this week's summary
        rows = get_week(chat_id)  # Fetch this week's transactions
        return format_summary(rows, "This Week")  # Format and return

    # If we get here, we didn't understand the message
    return "❓ I didn't understand that. Send 'help' to see what I can do."
