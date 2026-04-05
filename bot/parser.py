"""Parse chat messages into structured intents using regex."""
import re  # Regular expressions for pattern matching


def parse_message(text):
    """Turn a chat message into a dict with intent and data.

    Returns: {"intent": str, "amount": float, "category": str}
    """
    text = text.strip().lower()  # Normalize: remove whitespace, lowercase

    # Check for help/start commands first
    if text in ("help", "start", "/help", "/start"):  # Exact matches only
        return {"intent": "help"}  # Return help intent

    # Check for summary requests
    if text in ("summary", "today"):  # Daily summary triggers
        return {"intent": "summary_today"}  # Return today's summary intent
    if text == "week":  # Weekly summary trigger
        return {"intent": "summary_week"}  # Return week summary intent

    # Try to match a sale: "sold 50" or "sold 50 kenkey"
    sale = re.match(r"sold?\s+(\d+\.?\d*)\s*(.*)", text)  # Capture amount + optional category
    if sale:  # If the regex matched
        return {
            "intent": "sale",  # It's a sale
            "amount": float(sale.group(1)),  # The number after "sold"
            "category": sale.group(2).strip() or "general",  # Category or default
        }

    # Try to match an expense: "spent 30" or "expense 100 gas"
    expense = re.match(r"(?:spent|expense)\s+(\d+\.?\d*)\s*(.*)", text)  # Two trigger words
    if expense:  # If the regex matched
        return {
            "intent": "expense",  # It's an expense
            "amount": float(expense.group(1)),  # The number
            "category": expense.group(2).strip() or "general",  # Category or default
        }

    return {"intent": "unknown"}  # Nothing matched — we don't understand
