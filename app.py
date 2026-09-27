"""Sika Track — Telegram bookkeeping bot.

Supports two modes:
1. POLLING MODE (local development):
   - Bot asks Telegram "any new messages?" repeatedly
   - Used when WEBHOOK_URL is NOT set
   - Run with: python app.py

2. WEBHOOK MODE (production on Render):
   - Telegram sends messages TO our server via HTTP POST
   - Used when WEBHOOK_URL IS set
   - Run with: gunicorn app:flask_app (Render does this automatically)

How it decides which mode to use:
   - If WEBHOOK_URL environment variable is set → webhook mode
   - If WEBHOOK_URL is not set → polling mode

Why webhook mode for Render?
   Render's free tier spins down web services after 15 minutes of no HTTP traffic.
   With webhooks, every Telegram message IS an HTTP request, keeping the service
   alive while users are active. Polling mode makes no inbound HTTP requests,
   so Render would kill it immediately.
"""
import os       # Access environment variables
import logging  # Print helpful debug info to the terminal
import asyncio  # For running async code in webhook mode
import hmac     # Constant-time secret comparison
from collections import deque  # Remember recent update IDs to skip duplicates
from datetime import date      # "Today" for the evening summary

from dotenv import load_dotenv  # Load .env file into os.environ
from telegram import (  # Telegram types
    Update,                     # An incoming Telegram update
    BotCommand,                 # One entry in the ☰ Menu
    MenuButtonCommands,         # Makes ☰ open the command list
    ReplyKeyboardMarkup,        # Quick buttons under the keyboard
)
from telegram.error import Forbidden  # Raised when a user has blocked the bot
from telegram.ext import (      # Tools for building the bot
    ApplicationBuilder,         # Creates the bot application
    MessageHandler,             # Handles text messages
    CommandHandler,             # Handles /start, /help commands
    ContextTypes,               # Type hints for the callback context
    filters,                    # Filters to match specific message types
)
from bot.handlers import handle_message  # Our message processing logic
from bot.handlers import build_daily_summary  # Evening wrap-up text
from bot.database import get_daily_summary_recipients, set_daily_summary  # Summary audience
from bot.menu import MENU_COMMANDS, BUTTON_ROWS  # ☰ Menu commands + quick buttons

load_dotenv()  # Read .env file and set environment variables

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")       # Bot token from @BotFather
WEBHOOK_URL = os.getenv("WEBHOOK_URL")         # Set only in production (e.g., https://sika-track.onrender.com)
PORT = int(os.getenv("PORT", "8000"))          # Render sets PORT automatically; default 8000 for local
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")   # Proves a webhook call really came from Telegram
CRON_SECRET = os.getenv("CRON_SECRET")         # Protects the evening-summary trigger URL

# Set up logging so we can see what's happening
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ===========================================================================
# Telegram message handlers (same for both modes)
# ===========================================================================

ERROR_REPLY = "⚠️ Something went wrong on our side. Please try again in a moment."

# Quick buttons kept under the keyboard on every reply (see bot/menu.py)
QUICK_KEYBOARD = ReplyKeyboardMarkup(BUTTON_ROWS, resize_keyboard=True, is_persistent=True)


async def respond(update: Update, text: str):
    """Run one message through the bot and reply — never leaves the user in silence."""
    chat_id = update.message.chat.id                    # Unique ID for this chat
    first_name = update.message.chat.first_name or ""   # User's first name (may be None)
    logger.info("Message from %s (id=%d): %s", first_name, chat_id, text)
    try:
        reply = handle_message(chat_id, first_name, text)  # Process through parser + database
    except Exception:  # DB hiccup, bug, etc. — log it and tell the user to retry
        logger.exception("Failed to handle message from id=%d", chat_id)
        reply = ERROR_REPLY
    await update.message.reply_text(reply, reply_markup=QUICK_KEYBOARD)


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Called every time a user sends a text message (or taps a quick button)."""
    await respond(update, update.message.text)


# ---------------------------------------------------------------------------
# Menu button — the "Menu" / "/" button beside the message box in Telegram
# ---------------------------------------------------------------------------
# Each entry becomes a tappable command, so users don't have to type "help".
# The list lives in bot/menu.py so setup_webhook.py can register it too.


async def on_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start, /help and menu taps like /today — same logic as typing the word."""
    command = update.message.text.split()[0].lstrip("/").split("@")[0].lower()  # "/today@Bot" → "today"
    await respond(update, command)


async def register_menu(app):
    """Tell Telegram which commands to show in the chat's menu button."""
    await app.bot.set_my_commands([BotCommand(name, desc) for name, desc in MENU_COMMANDS])
    await app.bot.set_chat_menu_button(menu_button=MenuButtonCommands())  # Force ☰ to show commands
    logger.info("Menu commands registered with Telegram")


def build_app():
    """Create and configure the Telegram bot application.

    This is shared between polling and webhook modes — both need the same
    handlers registered.
    """
    app = ApplicationBuilder().token(TOKEN).post_init(register_menu).build()  # post_init runs in polling mode

    # Register handlers — order matters, commands checked first
    app.add_handler(CommandHandler(                      # /start, /help and menu taps (/today, ...)
        [name for name, _ in MENU_COMMANDS], on_command
    ))
    app.add_handler(MessageHandler(                      # Handle all other text
        filters.TEXT & ~filters.COMMAND, on_message
    ))

    return app


# ===========================================================================
# WEBHOOK MODE — for Render deployment
# ===========================================================================
# Flask handles HTTP requests. Telegram sends updates as POST requests
# to /webhook. We also have a /health endpoint that Render pings to
# check if the service is alive.

if WEBHOOK_URL:
    from flask import Flask, request, jsonify  # Only import Flask when needed

    flask_app = Flask(__name__)  # Create Flask web server
    telegram_app = None          # Will hold the Telegram bot application
    loop = asyncio.new_event_loop()  # One event loop reused for every request
    recent_update_ids = deque(maxlen=1000)  # Telegram resends on timeouts — skip repeats

    if not WEBHOOK_SECRET:
        logger.warning("WEBHOOK_SECRET is not set — anyone can POST fake updates to /webhook")

    def get_telegram_app():
        """Build + initialize the bot on first use (each gunicorn worker needs its own)."""
        global telegram_app
        if telegram_app is None:
            app = build_app()
            loop.run_until_complete(app.initialize())
            try:  # post_init only fires in polling mode, so register the menu here
                loop.run_until_complete(register_menu(app))
            except Exception:  # Menu is nice-to-have — never block message handling
                logger.exception("Failed to register menu commands")
            telegram_app = app
            logger.info("Telegram app initialized for webhook mode")
        return telegram_app

    def secret_matches(given, expected):
        """True only if a secret is configured and the given value matches it."""
        return bool(expected) and hmac.compare_digest(given or "", expected)

    @flask_app.route("/health", methods=["GET"])
    def health():
        """Health check endpoint — Render pings this to verify the service is up.

        Returns 200 OK so Render knows we're alive. If this fails, Render
        will restart the service.
        """
        return jsonify({"status": "ok", "bot": "Sika Track"}), 200

    @flask_app.route("/webhook", methods=["POST"])
    def webhook():
        """Receive updates from Telegram via webhook.

        When a user sends a message to the bot, Telegram sends an HTTP POST
        to this endpoint with the message data as JSON. We pass it to the
        python-telegram-bot library for processing.
        """
        if WEBHOOK_SECRET and not secret_matches(
            request.headers.get("X-Telegram-Bot-Api-Secret-Token"), WEBHOOK_SECRET
        ):
            logger.warning("Rejected webhook call with a missing or wrong secret")
            return "forbidden", 403  # Not from Telegram — ignore it

        app = get_telegram_app()

        # Parse the incoming JSON into a Telegram Update object
        update = Update.de_json(data=request.get_json(), bot=app.bot)

        # Telegram re-sends an update if we answered too slowly (e.g. cold start).
        # Processing it twice would record the same sale twice.
        if update.update_id in recent_update_ids:
            logger.info("Skipping duplicate update %d", update.update_id)
            return "ok", 200
        recent_update_ids.append(update.update_id)

        # Process the update; run_until_complete blocks until the handlers finish
        loop.run_until_complete(app.process_update(update))

        return "ok", 200  # Tell Telegram we received the update

    @flask_app.route("/cron/daily-summary", methods=["GET", "POST"])
    def daily_summary():
        """Send each active user their evening wrap-up. Call once a day from a cron service.

        Protected by CRON_SECRET, passed as ?key=... or an X-Cron-Secret header.
        """
        given = request.args.get("key") or request.headers.get("X-Cron-Secret")
        if not secret_matches(given, CRON_SECRET):
            return "forbidden", 403
        app = get_telegram_app()
        today = date.today()  # Ghana is on UTC, same as the server

        async def send_all():
            sent = 0
            for chat_id in get_daily_summary_recipients(today):
                text = build_daily_summary(chat_id, today)
                if not text:
                    continue
                try:
                    await app.bot.send_message(chat_id=chat_id, text=text)
                    sent += 1
                except Forbidden:  # User blocked the bot — stop sending to them
                    set_daily_summary(chat_id, False)
                except Exception:
                    logger.exception("Daily summary failed for id=%d", chat_id)
                await asyncio.sleep(0.05)  # Stay well under Telegram's ~30 msgs/sec limit
            return sent

        sent = loop.run_until_complete(send_all())
        logger.info("Daily summary sent to %d users", sent)
        return jsonify({"sent": sent}), 200

    @flask_app.route("/", methods=["GET"])
    def index():
        """Root endpoint — just confirms the bot is running.

        Useful for manual checks: visit https://sika-track.onrender.com/
        """
        return jsonify({
            "name": "Sika Track",
            "status": "running",
            "mode": "webhook",
        }), 200


# ===========================================================================
# POLLING MODE — for local development
# ===========================================================================

def main():
    """Start the bot in polling mode (local development only).

    Polling = the bot repeatedly asks Telegram "any new messages?"
    This is simpler for development but won't work on Render's free tier.
    """
    if not TOKEN:
        print("ERROR: Set TELEGRAM_BOT_TOKEN in your .env file")
        return

    print("Starting Sika Track bot in polling mode...")
    print("Press Ctrl+C to stop.\n")

    app = build_app()     # Create the bot application
    app.run_polling()     # Start polling (blocks until Ctrl+C)


if __name__ == "__main__":
    main()  # Run polling mode when executing directly: python app.py
