# =============================================================================
# Dockerfile for Sika Track — Telegram bookkeeping bot
# =============================================================================
# This builds a container that runs the bot in WEBHOOK mode on Render.
# Render builds this Docker image automatically when you push to GitHub.

# Start from a small Python image (slim = minimal OS, smaller download)
FROM python:3.11-slim

# Set the working directory inside the container
WORKDIR /app

# Copy requirements first — Docker caches this layer, so if requirements
# don't change, it skips reinstalling packages (faster deploys)
COPY requirements.txt .

# Install Python dependencies
# --no-cache-dir = don't store pip's cache (keeps the image smaller)
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Create the data directory for SQLite (used in local Docker testing only;
# on Render we use PostgreSQL via DATABASE_URL so this folder is unused)
RUN mkdir -p /app/data

# Tell Docker this container listens on port 8000
# (Render overrides this with $PORT, but it's good documentation)
EXPOSE 8000

# Run the Flask app with gunicorn in production
# - workers 1: Free tier has limited memory, 1 worker is enough for a bot
# - bind 0.0.0.0:$PORT: Listen on all interfaces, use Render's PORT variable
# - timeout 120: Allow up to 2 minutes per request (Telegram retries are slow)
# - flask_app: This is the Flask app object exported from app.py
#   (only created when WEBHOOK_URL is set — see app.py)
CMD gunicorn --workers 1 --bind 0.0.0.0:${PORT:-8000} --timeout 120 app:flask_app
