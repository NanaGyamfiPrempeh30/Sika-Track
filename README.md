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

### 6. Set the Webhook, Secret and Menu

Generate two random secrets:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"   # run twice
```

Add them on Render (Environment tab) **and** in your local `.env`:

| Variable | Purpose |
|----------|---------|
| `WEBHOOK_SECRET` | Telegram sends it with every update; anything without it is rejected |
| `CRON_SECRET` | Protects the evening-summary trigger URL |

Redeploy on Render, then run once from your computer:

```bash
python setup_webhook.py      # Sets webhook + secret + ☰ Menu commands
```

⚠️ Order matters: set `WEBHOOK_SECRET` on Render first, then run the script.
If the values don't match, the bot ignores every message.

### 7. Keep It Awake + Evening Summary (free, cron-job.org)

Render's free tier sleeps after 15 minutes, so the first reply can take 30–50s.
Create two jobs at [cron-job.org](https://cron-job.org):

| Job | URL | Schedule |
|-----|-----|----------|
| Keep awake | `https://<your-app>.onrender.com/health` | Every 10 minutes |
| Evening summary | `https://<your-app>.onrender.com/cron/daily-summary?key=<CRON_SECRET>` | Daily, 19:00 GMT |

The summary only goes to users who logged something that day. Users can send
`summary off` to stop it.

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
| ➕ Sale / ➖ Expense buttons | Tap, then type `50 kenkey` |
| `summary off` / `summary on` | Stop or restart the evening summary |
