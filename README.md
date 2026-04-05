# Sika Track

A Telegram bookkeeping bot for informal businesses in Ghana. Track daily sales and expenses via simple chat messages.

## Setup

### 1. Create a Telegram Bot

- Message [@BotFather](https://t.me/BotFather) on Telegram
- Send `/newbot` and follow the prompts
- Copy the bot token you receive

### 2. Install Dependencies

```bash
python -m venv venv          # Create a virtual environment
source venv/bin/activate     # Activate it (Linux/Mac)
# venv\Scripts\activate      # Activate it (Windows)
pip install -r requirements.txt
```

### 3. Configure Environment

```bash
cp .env.example .env         # Copy the example file
# Edit .env and add your TELEGRAM_BOT_TOKEN and WEBHOOK_URL
```

### 4. Run Locally

```bash
python app.py                # Starts Flask dev server on port 5000
```

### 5. Run with Docker

```bash
docker build -t sika-track .
docker run -p 8000:8000 --env-file .env sika-track
```

### 6. Set the Webhook

Tell Telegram where to send updates:

```bash
curl "https://api.telegram.org/bot<YOUR_TOKEN>/setWebhook?url=<YOUR_WEBHOOK_URL>"
```

## Usage

Send these messages to your bot on Telegram:

| Message | What it does |
|---------|-------------|
| `sold 50` | Records a GHS 50 sale |
| `sold 200 kenkey` | Records a GHS 200 sale (category: kenkey) |
| `spent 30 gas` | Records a GHS 30 expense (category: gas) |
| `expense 100` | Records a GHS 100 expense |
| `today` or `summary` | Shows today's sales, expenses, and profit |
| `week` | Shows this week's summary |
| `help` | Shows usage instructions |
