"""Commands shown in the Telegram Menu button beside the message box.

Order here = order shown in the menu. "delete" (wipe all data) is left out
on purpose so nobody taps it by accident.
"""

MENU_COMMANDS = [
    ("help", "📖 How to use Sika Track"),
    ("today", "📊 Today's summary"),
    ("profit", "💰 Today's profit or loss"),
    ("week", "📅 Last 7 days summary"),
    ("month", "🗓️ This month so far"),
    ("list", "📋 Last 10 transactions"),
    ("undo", "↩️ Remove last entry"),
    ("start", "👋 Welcome & privacy info"),
]

# Quick buttons kept under the keyboard (one-tap actions). Each row = one line.
BUTTON_ROWS = [
    ["➕ Sale", "➖ Expense"],
    ["📊 Today", "💰 Profit"],
    ["📋 List", "📖 Help"],
]

# What each button does — mapped to the same text a user would type.
BUTTON_ACTIONS = {
    "➕ Sale": "sale prompt",       # Asks "how much?" then records a sale
    "➖ Expense": "expense prompt",  # Asks "how much?" then records an expense
    "📊 Today": "today",
    "💰 Profit": "profit",
    "📋 List": "list",
    "📖 Help": "help",
}
