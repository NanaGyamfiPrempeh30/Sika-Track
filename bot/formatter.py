"""Format transaction data into clean Telegram messages with emoji."""

# Welcome text with privacy notice — shown when user sends /start
START_TEXT = (
    "👋 Welcome to Sika Track!\n"  # Greeting with wave emoji
    "I help you track daily sales and expenses.\n\n"  # One-line description
    "🔒 Your data is private. Only you can see your records. "  # Privacy notice
    "We don't share your information with anyone. "  # Data policy
    "Send 'delete' to erase all your data at any time.\n\n"  # Deletion option
    "Send 'help' to see all available commands."  # Point to help
)

# Full command reference — shown when user sends /help or "help"
HELP_TEXT = (
    "📖 Sika Track — Commands\n\n"  # Header
    "💰 Record a sale:\n"  # Sales section
    "  sold 50\n"  # Example: basic sale
    "  made 200 kenkey\n"  # Example: sale with category
    "  Keywords: sold, sale, income, received,\n"  # All sale trigger words
    "  got, earn, made\n\n"  # (continued)
    "💸 Record an expense:\n"  # Expenses section
    "  spent 30 gas\n"  # Example: expense with category
    "  paid 100 electricity\n"  # Example: paid keyword
    "  Keywords: spent, expense, paid, bought, cost\n\n"  # All expense triggers
    "📊 View summaries:\n"  # Summaries section
    "  today — today's summary\n"  # Daily summary
    "  yesterday — yesterday\n"  # Yesterday shortcut
    "  week — last 7 days\n"  # Weekly summary
    "  monday / tuesday / ... — that day\n"  # Day-of-week summary
    "  3 days — last 3 days\n"  # Rolling N-day window
    "  month — this month so far\n"  # Monthly summary
    "  5 april — a specific date\n"  # Specific date lookup
    "  Keywords: summary, report, total,\n"  # All summary triggers
    "  balance, how much\n\n"  # (continued)
    "↩️ Undo last entry:\n"  # Undo section
    "  undo — remove last transaction\n"  # Primary undo keyword
    "  Also: delete last, cancel last, remove last\n\n"  # Undo aliases
    "🗑️ Delete all data:\n"  # Deletion section
    "  delete — erase everything"  # Data wipe command
)


def format_summary(rows, label):
    """Turn a list of transaction rows into a readable summary with emoji.

    Args:
        rows: list of dicts with 'type' and 'amount' keys
        label: date range description shown under the header
               (e.g. "Today — Wednesday, April 16" or "Monday, April 13 to Wednesday, April 15")
    """
    if not rows:  # No transactions found for this period
        return f"📭 No transactions found.\n📅 {label}"  # Empty state with date context

    total_sales = 0.0  # Running total for sales
    total_expenses = 0.0  # Running total for expenses

    for row in rows:  # Loop through each transaction
        if row["type"] == "sale":  # It's a sale
            total_sales += row["amount"]  # Add to sales total
        else:  # It's an expense
            total_expenses += row["amount"]  # Add to expenses total

    profit = total_sales - total_expenses  # Calculate profit (or loss)
    emoji = "📈" if profit >= 0 else "📉"  # Up arrow for profit, down for loss
    profit_label = "Profit" if profit >= 0 else "Loss"  # Word label for bottom line

    # Build the summary message with date range header
    return (
        f"📊 Sika Track — Summary\n"  # App-branded header
        f"📅 {label}\n\n"  # Date range on its own line
        f"💰 Sales: GHS {total_sales:.2f}\n"  # Total sales
        f"💸 Expenses: GHS {total_expenses:.2f}\n"  # Total expenses
        f"{emoji} {profit_label}: GHS {abs(profit):.2f}"  # Profit or loss
    )
