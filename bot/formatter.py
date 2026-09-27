"""Format transaction data into clean Telegram messages with emoji."""

# Welcome text with privacy notice — shown when user sends /start
START_TEXT = (
    "👋 Welcome to Sika Track!\n"  # Greeting with wave emoji
    "I help you track daily sales and expenses.\n\n"  # One-line description
    "🔒 Your data is private. Only you can see your records. "  # Privacy notice
    "We don't share your information with anyone. "  # Data policy
    "Send 'delete' to erase all your data at any time.\n\n"  # Deletion option
    "Use the buttons below to log a sale or expense in one tap, "  # Quick buttons
    "or tap ☰ Menu / send 'help' to see all commands."  # Point to menu + help
)

# Full command reference — shown when user sends /help or "help"
HELP_TEXT = (
    "📖 Sika Track — Commands\n\n"  # Header
    "⚡ Quick buttons: tap ➕ Sale or ➖ Expense,\n"  # One-tap logging
    "  then type the amount, e.g. 50 kenkey\n\n"  # Second step
    "💰 Record a sale:\n"  # Sales section
    "  sold 50\n"  # Example: basic sale
    "  made 200 kenkey\n"  # Example: sale with category
    "  Keywords: sold, sell, sale, income,\n"  # All sale trigger words
    "  received, got, earn, made\n\n"  # (continued)
    "💸 Record an expense:\n"  # Expenses section
    "  spent 30 gas\n"  # Example: expense with category
    "  paid 100 electricity\n"  # Example: paid keyword
    "  Keywords: spent, spend, sent, expense,\n"  # All expense triggers
    "  paid, pay, bought, buy, cost\n\n"  # (continued)
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
    "💰 Quick profit check:\n"  # Profit one-liner
    "  profit — today's profit (or loss)\n"  # Default: today
    "  profit yesterday — yesterday's bottom line\n"  # Yesterday variant
    "  profit this week — week so far\n"  # Week variant
    "  profit this month — month so far\n\n"  # Month variant
    "📂 Category spending:\n"  # New: category-specific totals
    "  food this month — food totals this month\n"  # Example with explicit period
    "  kenkey this week — kenkey sales this week\n"  # Example for sales category
    "  gas today — gas spend today\n"  # Single-day category query
    "  how much food — defaults to this month\n"  # Defaulted period
    "  Periods: today, yesterday, week, month\n\n"  # Supported periods
    "↩️ Undo last entry:\n"  # Undo section
    "  undo — remove last transaction\n"  # Primary undo keyword
    "  Also: delete last, cancel last, remove last\n"  # Undo aliases
    "  Then send 'yes undo' to confirm\n\n"  # Confirmation step for undo
    "📋 Remove or edit a specific entry:\n"  # Numbered-list removal + edit
    "  list — show your last 10 transactions\n"  # Step 1: see numbered list
    "  remove 1 — delete the first one\n"  # Step 2a: delete by number
    "  edit 1 to 500 — change its amount to 500\n"  # Step 2b: edit amount by number
    "  Also: recent, transactions (same as list)\n"  # Aliases for the list command
    "  Also: delete 1 / change 1 to 500\n"  # Alias for remove + edit
    "  Then send 'yes' to confirm\n\n"  # Confirmation step
    "🌙 Evening summary:\n"  # Automatic nightly wrap-up
    "  Sent each evening on days you log something\n"  # When it arrives
    "  summary off / summary on — stop or restart it\n\n"  # Opt-out toggle
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
    bottom_line = f"{emoji} {profit_label}: GHS {abs(profit):.2f}"  # Profit or loss
    if total_sales == 0:  # Expenses only — sales were likely forgotten, not a real loss
        bottom_line = "🤔 No sales logged, so no profit to show.\nMade any? Tap ➕ Sale to add them."

    # Build the summary message with date range header
    return (
        f"📊 Sika Track — Summary\n"  # App-branded header
        f"📅 {label}\n\n"  # Date range on its own line
        f"💰 Sales: GHS {total_sales:.2f}\n"  # Total sales
        f"💸 Expenses: GHS {total_expenses:.2f}\n"  # Total expenses
        f"{bottom_line}"  # Profit, loss, or a nudge to log sales
    )


def format_category_summary(rows, category, label):
    """Format a per-category total over a date range.

    If only sales exist → show sales line.
    If only expenses exist → show expenses line.
    If both → show both lines.
    If none → friendly empty-state message.

    Args:
        rows: list of dicts with 'type' and 'amount' keys (already filtered to category)
        category: original category name from the user's query (preserves their casing)
        label: human-readable period label like 'This month (Apr 1 – Apr 16)'
    """
    if not rows:  # No transactions matched this category in the requested range
        # Plain-language empty state, mirrors the spec's exact phrasing
        period_word = label.split(" (")[0].lower()  # 'this month', 'today', etc.
        return f"No transactions found for '{category}' {period_word}."

    sales_total = 0.0   # Sum of sale amounts in this category
    sales_count = 0     # Number of sale transactions
    exp_total = 0.0     # Sum of expense amounts in this category
    exp_count = 0       # Number of expense transactions

    for row in rows:  # Aggregate one row at a time
        if row["type"] == "sale":  # Sale row contributes to sales totals
            sales_total += row["amount"]
            sales_count += 1
        else:  # Anything else is treated as an expense
            exp_total += row["amount"]
            exp_count += 1

    # Header lines shared across all output variants
    lines = [
        f"📂 Category: {category}",  # Echo the user's category name
        f"📅 {label}",                # The resolved period with date range
        "",                            # Blank line separator before totals
    ]

    if sales_count and exp_count:  # Mixed category — show both rows
        lines.append(
            f"💰 Total sales: GHS {sales_total:.2f} ({sales_count} transactions)"
        )
        lines.append(
            f"💸 Total expenses: GHS {exp_total:.2f} ({exp_count} transactions)"
        )
    elif sales_count:  # Sales only — single line with count
        lines.append(f"💰 Total sales: GHS {sales_total:.2f}")
        lines.append(f"📝 {sales_count} transactions")
    else:  # Expenses only — single line with count
        lines.append(f"💸 Total expenses: GHS {exp_total:.2f}")
        lines.append(f"📝 {exp_count} transactions")

    return "\n".join(lines)  # Join with newlines for the final message


def format_transaction_list(rows, format_dt):
    """Render a numbered list of recent transactions for the 'list' command.

    Sales use the ✅ marker, expenses use 💸, mirroring the rest of the bot.
    The trailing hint tells the user how to delete one — that's the whole
    point of showing the numbers.

    Args:
        rows: list of transaction dicts (id, type, amount, category, created_at),
              already ordered newest-first by the caller.
        format_dt: callable that turns a created_at value into a display string
                   like 'Wed, Apr 16 at 2:35 PM'. Passed in to avoid pulling
                   handler-internal helpers into this module.
    """
    lines = ["📋 Recent transactions:"]  # Header line

    for index, row in enumerate(rows, start=1):  # 1-based numbering for the user
        marker = "✅ Sale" if row["type"] == "sale" else "💸 Expense"  # Type label + emoji
        when = format_dt(row["created_at"])  # 'Wed, Apr 16 at 2:35 PM'
        lines.append(  # One line per transaction
            f"{index}. {marker} — GHS {row['amount']:.2f} "
            f"({row['category']}) {when}"
        )

    lines.append("")  # Blank line before the deletion hint for readability
    lines.append("To delete one, send: remove 1")  # Tell the user how to act on the list
    return "\n".join(lines)  # Final message
