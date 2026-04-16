"""Parse chat messages into structured intents using regex.

Supports:
- Sale recording with multiple keywords (sold, sale, income, received, got, earn, made)
- Expense recording with multiple keywords (spent, expense, paid, bought, cost)
- Flexible date summaries (today, yesterday, day names, N days, month, specific dates)
- Undo / delete last transaction
- Full data deletion with confirmation
- Summary aliases (summary, report, total, balance, how much)
"""
import re  # Regular expressions for pattern matching
from datetime import date, timedelta  # Date math for flexible summaries


# Day name → weekday number (Monday=0, Sunday=6) — for "monday", "tuesday" etc.
DAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

# Month name/abbreviation → month number — for specific date parsing like "5 april"
MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6,
    "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9, "sep": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}


def _fmt(d):
    """Format a date as 'Monday, April 13' — no leading zeros, human-friendly."""
    return f"{d.strftime('%A')}, {d.strftime('%B')} {d.day}"


def parse_message(text):
    """Turn a chat message into a dict with intent and data.

    Returns one of:
      {"intent": "help"}
      {"intent": "start"}
      {"intent": "sale", "amount": float, "category": str}
      {"intent": "expense", "amount": float, "category": str}
      {"intent": "summary", "start": date, "end": date, "label": str}
      {"intent": "undo"}
      {"intent": "undo_confirm"}
      {"intent": "delete"}
      {"intent": "delete_confirm"}
      {"intent": "unknown"}
    """
    text = text.strip().lower()  # Normalize: remove whitespace, lowercase

    # --- Confirmation intents — checked first to avoid collisions with other keywords ---
    if text == "yes delete":  # Confirms full data deletion
        return {"intent": "delete_confirm"}
    if text == "yes undo":  # Confirms removing last transaction
        return {"intent": "undo_confirm"}

    # --- Help and start commands ---
    if text in ("help", "/help"):  # Show command reference
        return {"intent": "help"}
    if text in ("start", "/start"):  # Show welcome message + privacy notice
        return {"intent": "start"}

    # --- Undo / delete last — checked before "delete" so "delete last" isn't caught ---
    if text in ("undo", "delete last", "cancel last", "remove last"):  # Remove last entry
        return {"intent": "undo"}

    # --- Full data deletion (exact match only) ---
    if text == "delete":  # Request to erase all user data
        return {"intent": "delete"}

    # --- Summary: exact keyword matches for today ---
    # "today", "summary", "report", "total", "balance", "how much" all show today's summary
    if text in ("summary", "today", "report", "total", "balance") or text == "how much":
        today = date.today()
        return {
            "intent": "summary",
            "start": today,
            "end": today,
            "label": f"Today — {_fmt(today)}",  # e.g. "Today — Wednesday, April 16"
        }

    # "week" → last 7 days summary
    if text == "week":
        today = date.today()
        start = today - timedelta(days=6)  # 7-day window including today
        return {
            "intent": "summary",
            "start": start,
            "end": today,
            "label": f"{_fmt(start)} to {_fmt(today)}",
        }

    # "yesterday" → yesterday's summary
    if text == "yesterday":
        yesterday = date.today() - timedelta(days=1)
        return {
            "intent": "summary",
            "start": yesterday,
            "end": yesterday,
            "label": f"Yesterday — {_fmt(yesterday)}",
        }

    # --- Day names: "monday", "tuesday" etc. → that day this week ---
    if text in DAYS:
        today = date.today()
        week_start = today - timedelta(days=today.weekday())  # Monday of current week
        target = week_start + timedelta(days=DAYS[text])  # Target day within the week
        return {
            "intent": "summary",
            "start": target,
            "end": target,
            "label": _fmt(target),  # e.g. "Monday, April 13"
        }

    # --- "N days" or "last N days" → rolling window of past N days ---
    days_match = re.match(r"(?:last\s+)?(\d+)\s*days?$", text)  # "3 days", "last 5 days"
    if days_match:
        n = int(days_match.group(1))  # Number of days requested
        today = date.today()
        start = today - timedelta(days=n - 1)  # N days including today
        return {
            "intent": "summary",
            "start": start,
            "end": today,
            "label": f"Last {n} days — {_fmt(start)} to {_fmt(today)}",
        }

    # --- "this month" or "month" → current calendar month so far ---
    if text in ("this month", "month"):
        today = date.today()
        start = today.replace(day=1)  # First day of current month
        return {
            "intent": "summary",
            "start": start,
            "end": today,
            "label": f"{today.strftime('%B')} {today.year} — {_fmt(start)} to {_fmt(today)}",
        }

    # --- Specific date: "5 april", "april 5" (also works with abbreviations like "apr") ---
    # Pattern 1: day then month — "5 april", "12 mar"
    date_match = re.match(r"(\d{1,2})\s+([a-z]+)$", text)  # Number + word at end of string
    if date_match and date_match.group(2) in MONTHS:
        day_num = int(date_match.group(1))
        month_num = MONTHS[date_match.group(2)]
        try:
            target = date(date.today().year, month_num, day_num)  # Assume current year
            return {
                "intent": "summary",
                "start": target,
                "end": target,
                "label": _fmt(target),  # e.g. "Saturday, April 5"
            }
        except ValueError:
            pass  # Invalid date like "31 february" — fall through to unknown

    # Pattern 2: month then day — "april 5", "mar 12"
    date_match = re.match(r"([a-z]+)\s+(\d{1,2})$", text)  # Word + number at end of string
    if date_match and date_match.group(1) in MONTHS:
        month_num = MONTHS[date_match.group(1)]
        day_num = int(date_match.group(2))
        try:
            target = date(date.today().year, month_num, day_num)  # Assume current year
            return {
                "intent": "summary",
                "start": target,
                "end": target,
                "label": _fmt(target),
            }
        except ValueError:
            pass  # Invalid date — fall through to unknown

    # --- Sale keywords: sold, sale, income, received, got, earn/earned, made ---
    # Matches: "sold 50", "made 200 kenkey", "income 1000 consulting", etc.
    sale = re.match(
        r"(?:sold?|sale|income|received|got|earn(?:ed)?|made)\s+(\d+\.?\d*)\s*(.*)",
        text,
    )  # Keyword + amount + optional category
    if sale:
        return {
            "intent": "sale",
            "amount": float(sale.group(1)),  # The numeric amount
            "category": sale.group(2).strip() or "general",  # Category or default
        }

    # --- Expense keywords: spent, expense, paid, bought, cost ---
    # Matches: "spent 30 gas", "paid 100 electricity", "bought 50 supplies", etc.
    expense = re.match(
        r"(?:spent|expense|paid|bought|cost)\s+(\d+\.?\d*)\s*(.*)",
        text,
    )  # Keyword + amount + optional category
    if expense:
        return {
            "intent": "expense",
            "amount": float(expense.group(1)),  # The numeric amount
            "category": expense.group(2).strip() or "general",  # Category or default
        }

    return {"intent": "unknown"}  # Nothing matched — we don't understand
