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

from dotenv import load_dotenv  # Load .env file into os.environ
from telegram import Update, BotCommand  # Incoming update + menu command entries
from telegram.ext import (      # Tools for building the bot
    ApplicationBuilder,         # Creates the bot application
    MessageHandler,             # Handles text messages
    CommandHandler,             # Handles /start, /help commands
    ContextTypes,               # Type hints for the callback context
    filters,                    # Filters to match specific message types
)
from bot.handlers import handle_message  # Our message processing logic

load_dotenv()  # Read .env file and set environment variables

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")       # Bot token from @BotFather
WEBHOOK_URL = os.getenv("WEBHOOK_URL")         # Set only in production (e.g., https://sika-track.onrender.com)
PORT = int(os.getenv("PORT", "8000"))          # Render sets PORT automatically; default 8000 for local

# Set up logging so we can see what's happening
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ===========================================================================
# Telegram message handlers (same for both modes)
# ===========================================================================

async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Called every time a user sends a text message to the bot."""
    chat_id = update.message.chat.id                    # Unique ID for this chat
    first_name = update.message.chat.first_name or ""   # User's first name (may be None)
    text = update.message.text                           # The raw text the user sent
    logger.info("Message from %s (id=%d): %s", first_name, chat_id, text)
    reply = handle_message(chat_id, first_name, text)    # Process through parser + database
    await update.message.reply_text(reply)               # Send reply back to user


async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Called when user sends /start command — shows welcome + privacy notice."""
    chat_id = update.message.chat.id
    first_name = update.message.chat.first_name or ""
    logger.info("/start from %s (id=%d)", first_name, chat_id)
    reply = handle_message(chat_id, first_name, "start")  # Welcome with privacy notice
    await update.message.reply_text(reply)


async def on_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Called when user sends /help command — shows all available commands."""
    chat_id = update.message.chat.id
    first_name = update.message.chat.first_name or ""
    logger.info("/help from %s (id=%d)", first_name, chat_id)
    reply = handle_message(chat_id, first_name, "help")  # Full command reference
    await update.message.reply_text(reply)


# ---------------------------------------------------------------------------
# Menu button — the "Menu" / "/" button beside the message box in Telegram
# ---------------------------------------------------------------------------
# Each entry becomes a tappable command, so users don't have to type "help".
# Order here = order shown in the menu. "delete" (wipe all data) is left out
# on purpose so nobody taps it by accident.
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


async def on_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle menu taps like /today — runs the same logic as typing 'today'."""
    chat_id = update.message.chat.id
    first_name = update.message.chat.first_name or ""
    command = update.message.text.split()[0].lstrip("/").split("@")[0].lower()  # "/today@Bot" → "today"
    logger.info("/%s from %s (id=%d)", command, first_name, chat_id)
    reply = handle_message(chat_id, first_name, command)  # Reuse the text-keyword flow
    await update.message.reply_text(reply)


async def register_menu(app):
    """Tell Telegram which commands to show in the chat's menu button."""
    await app.bot.set_my_commands([BotCommand(name, desc) for name, desc in MENU_COMMANDS])
    logger.info("Menu commands registered with Telegram")


def build_app():
    """Create and configure the Telegram bot application.

    This is shared between polling and webhook modes — both need the same
    handlers registered.
    """
    app = ApplicationBuilder().token(TOKEN).post_init(register_menu).build()  # post_init runs in polling mode

    # Register handlers — order matters, commands checked first
    app.add_handler(CommandHandler("start", on_start))   # Handle /start — welcome + privacy
    app.add_handler(CommandHandler("help", on_help))     # Handle /help — command reference
    app.add_handler(CommandHandler(                      # Handle other menu taps (/today, /list, ...)
        [name for name, _ in MENU_COMMANDS if name not in ("start", "help")], on_menu_command
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
        global telegram_app

        if telegram_app is None:
            # First request — initialize the Telegram bot
            # We do this lazily because gunicorn workers each need their own instance
            telegram_app = build_app()
            asyncio.get_event_loop().run_until_complete(telegram_app.initialize())
            try:  # post_init only fires in polling mode, so register the menu here
                asyncio.get_event_loop().run_until_complete(register_menu(telegram_app))
            except Exception:  # Menu is nice-to-have — never block message handling
                logger.exception("Failed to register menu commands")
            logger.info("Telegram app initialized for webhook mode")

        # Parse the incoming JSON into a Telegram Update object
        update = Update.de_json(data=request.get_json(), bot=telegram_app.bot)

        # Process the update asynchronously
        # run_until_complete blocks until the handlers finish
        asyncio.get_event_loop().run_until_complete(
            telegram_app.process_update(update)
        )

        return "ok", 200  # Tell Telegram we received the update

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
