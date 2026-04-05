"""Format transaction data into clean Telegram messages with emoji."""

# Help text shown when user types "help", "/start", or "/help"
HELP_TEXT = (
    "👋 Welcome to Sika Track!\n"  # Greeting with wave emoji
    "I help you track daily sales and expenses.\n\n"  # One-line description
    "💰 Record a sale:\n"  # Sales section
    "  sold 50\n"  # Example without category
    "  sold 200 kenkey\n\n"  # Example with category
    "💸 Record an expense:\n"  # Expenses section
    "  spent 30 gas\n"  # Example with category
    "  expense 100\n\n"  # Example without category
    "📊 View summaries:\n"  # Summaries section
    "  today — today's summary\n"  # Daily summary
    "  week — this week's summary"  # Weekly summary
)


def format_summary(rows, period):
    """Turn a list of transaction rows into a readable summary with emoji."""
    if not rows:  # No transactions found
        return f"📭 No transactions for {period}."  # Tell the user with empty mailbox emoji

    total_sales = 0.0  # Running total for sales
    total_expenses = 0.0  # Running total for expenses

    for row in rows:  # Loop through each transaction
        if row["type"] == "sale":  # It's a sale
            total_sales += row["amount"]  # Add to sales total
        else:  # It's an expense
            total_expenses += row["amount"]  # Add to expenses total

    profit = total_sales - total_expenses  # Calculate profit (or loss)
    emoji = "📈" if profit >= 0 else "📉"  # Up arrow for profit, down for loss
    label = "Profit" if profit >= 0 else "Loss"  # Word label for the bottom line

    # Build the summary message line by line
    return (
        f"📊 — {period} —\n"  # Header with period name
        f"💰 Sales: GHS {total_sales:.2f}\n"  # Total sales
        f"💸 Expenses: GHS {total_expenses:.2f}\n"  # Total expenses
        f"{emoji} {label}: GHS {abs(profit):.2f}"  # Profit or loss
    )
