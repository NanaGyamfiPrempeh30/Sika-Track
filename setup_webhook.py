"""Register the webhook URL with Telegram — run this ONCE after your first Render deploy.

Usage:
    python setup_webhook.py

What this does:
    Tells Telegram: "Send all messages for my bot to https://sika-track.onrender.com/webhook"
    After this, Telegram will POST every message to your Render server instead of
    requiring the bot to poll for updates.

You only need to run this once. Run it again if you change your Render URL.

Requirements:
    - TELEGRAM_BOT_TOKEN must be set in your .env file
    - WEBHOOK_URL must be set in your .env file (e.g., https://sika-track.onrender.com)
"""
import os
import requests  # HTTP client to call the Telegram API
from dotenv import load_dotenv  # Load .env file

load_dotenv()  # Read .env file

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")  # Your bot token
WEBHOOK_URL = os.getenv("WEBHOOK_URL")   # Your Render URL (e.g., https://sika-track.onrender.com)

if not TOKEN:
    print("ERROR: Set TELEGRAM_BOT_TOKEN in your .env file")
    exit(1)

if not WEBHOOK_URL:
    print("ERROR: Set WEBHOOK_URL in your .env file")
    print("Example: WEBHOOK_URL=https://sika-track.onrender.com")
    exit(1)

# The full webhook endpoint — Telegram will POST updates here
webhook_endpoint = f"{WEBHOOK_URL}/webhook"

# Call the Telegram API to register the webhook
# Docs: https://core.telegram.org/bots/api#setwebhook
print(f"Setting webhook to: {webhook_endpoint}")
response = requests.get(
    f"https://api.telegram.org/bot{TOKEN}/setWebhook",
    params={"url": webhook_endpoint},  # Tell Telegram where to send updates
)

# Show the result
result = response.json()
if result.get("ok"):
    print("Webhook set successfully!")
    print(f"Telegram will now send messages to: {webhook_endpoint}")
else:
    print(f"ERROR: {result}")
    print("Check your token and webhook URL.")
