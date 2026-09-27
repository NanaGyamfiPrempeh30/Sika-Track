"""Check whether Telegram can deliver messages to the bot — run when the bot stops replying.

Usage:
    python check_webhook.py

Asks Telegram for the webhook status and explains any error in plain words.
Needs TELEGRAM_BOT_TOKEN in your .env file.
"""
import os
import re
from datetime import datetime, timezone

import requests  # HTTP client to call the Telegram API
from dotenv import load_dotenv  # Load .env file

load_dotenv()
TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
if not TOKEN:
    print("ERROR: Set TELEGRAM_BOT_TOKEN in your .env file")
    exit(1)

# Docs: https://core.telegram.org/bots/api#getwebhookinfo
info = requests.get(f"https://api.telegram.org/bot{TOKEN}/getWebhookInfo").json().get("result", {})

url = info.get("url") or "(none)"
waiting = info.get("pending_update_count", 0)
error = info.get("last_error_message")

print(f"Webhook URL:       {url}")
print(f"Messages waiting:  {waiting}")

if not info.get("url"):
    print("\n❌ No webhook set. Run: python setup_webhook.py")
elif not url.endswith("/webhook") or "//webhook" in url:
    print("\n❌ URL looks wrong — it must end in /webhook (no double slash). Fix WEBHOOK_URL, rerun setup_webhook.py")
elif error:
    when = datetime.fromtimestamp(info.get("last_error_date", 0), timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"Last error:        {error} ({when})")
    if "403" in error:
        print("\n❌ Secret mismatch: WEBHOOK_SECRET in .env is not the same as on Render.")
        print("   Copy the exact value from Render into .env, then rerun: python setup_webhook.py")
    elif "404" in error:
        print("\n❌ Wrong address: check WEBHOOK_URL, then rerun: python setup_webhook.py")
    elif re.search(r"\b5\d\d\b", error) or "timeout" in error.lower() or "connection" in error.lower():
        print("\n⚠️ The server errored or was asleep. Check the Render logs for the error.")
    else:
        print("\n⚠️ See the error above and the Render logs.")
    if waiting == 0:
        print("   (No messages waiting — this error may be old and already fixed.)")
else:
    print("\n✅ Telegram is delivering messages with no errors.")
