import json
import os
import requests
import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
import socket
from contextlib import closing
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    PicklePersistence
)
from dotenv import load_dotenv
import logging

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# File to store alerts and persistence data
ALERT_FILE = 'prices.json'
PERSISTENCE_FILE = 'bot_persistence.pickle'

def load_alerts():
    try:
        if os.path.exists(ALERT_FILE):
            with open(ALERT_FILE, 'r') as f:
                return json.load(f)
        return {}
    except Exception as e:
        logger.error(f"Error loading alerts: {e}")
        return {}

def save_alerts(data):
    try:
        with open(ALERT_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving alerts: {e}")

# Your Telegram bot token and Railway ping URL
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set!")

PING_URL = os.getenv("PING_URL")  # e.g., "https://your-app-name.up.railway.app"

# Allowed users (Telegram User IDs)
ALLOWED_USERS = {5817239686, 5274796002}

# Supported coin symbol → CoinGecko ID
SYMBOL_MAP = {
    "btc": "bitcoin",
    "eth": "ethereum",
    "bnb": "binancecoin",
    "sol": "solana",
    "ada": "cardano",
    "doge": "dogecoin",
    "xrp": "ripple",
    "meme": "meme",
    "moxie": "moxie",
    "degen": "degen-base",
}

def find_available_port(start_port=10001, max_attempts=20):
    """Find an available port starting from start_port"""
    for port in range(start_port, start_port + max_attempts):
        try:
            with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
                s.bind(('0.0.0.0', port))
                return port
        except socket.error:
            continue
    raise RuntimeError(f"No available ports found between {start_port}-{start_port + max_attempts - 1}")

# [All your existing command functions remain unchanged...]

async def check_prices(context: ContextTypes.DEFAULT_TYPE):
    try:
        alerts = load_alerts()
        if not alerts:
            logger.debug("No alerts to check")
            return

        coins = list({alert['coin'] for alerts in alerts.values() for alert in alerts})
        if not coins:
            return

        logger.info(f"Checking prices for {len(coins)} coins...")
        
        try:
            response = requests.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": ",".join(coins), "vs_currencies": "usd"},
                timeout=15
            )
            response.raise_for_status()
            prices = response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch prices for alert check: {e}")
            return
        except Exception as e:
            logger.error(f"Unexpected error fetching prices: {e}")
            return

        for user_id, user_alerts in list(alerts.items()):
            to_remove = []
            for i, alert in enumerate(user_alerts):
                current = prices.get(alert["coin"], {}).get("usd")
                if current is None:
                    continue
                    
                if (alert["direction"] == "above" and current >= alert["price"]) or \
                   (alert["direction"] == "below" and current <= alert["price"]):
                    try:
                        await context.bot.send_message(
                            chat_id=int(user_id),
                            text=f"🚨 {alert['symbol'].upper()} is ${current:.5f}, hit {alert['direction']} ${alert['price']}!"
                        )
                        to_remove.append(i)
                        logger.info(f"Alert triggered for user {user_id}: {alert['symbol']} {alert['direction']} {alert['price']}")
                    except Exception as e:
                        logger.error(f"Failed to send alert to user {user_id}: {e}")

            for i in reversed(to_remove):
                user_alerts.pop(i)
                
            if user_alerts:
                alerts[user_id] = user_alerts
            else:
                alerts.pop(user_id)
                
        save_alerts(alerts)
        
    except Exception as e:
        logger.error(f"Error in check_prices job: {e}")

async def ping_self():
    if not PING_URL:
        logger.info("No PING_URL set, skipping self-pinging")
        return
        
    logger.info(f"Starting self-pinging to {PING_URL} every 5 minutes")
    while True:
        try:
            logger.debug(f"Pinging {PING_URL}...")
            response = requests.get(PING_URL, timeout=10)
            logger.info(f"Ping successful (Status: {response.status_code})")
        except requests.exceptions.RequestException as e:
            logger.error(f"Ping failed: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected ping error: {str(e)}")
            
        await asyncio.sleep(300)  # every 5 minutes

class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Pong")
        logger.debug("Received ping request")

def run_ping_server():
    def server_thread():
        port = find_available_port()
        logger.info(f"Starting ping server on port {port}")
        
        # Update the PING_URL if it exists (for Railway/Heroku)
        global PING_URL
        if PING_URL:
            # Handle both http:// and https:// URLs
            if PING_URL.startswith('http://'):
                base_url = PING_URL.replace('http://', '').split(':')[0]
                PING_URL = f"http://{base_url}:{port}"
            elif PING_URL.startswith('https://'):
                base_url = PING_URL.replace('https://', '').split(':')[0]
                PING_URL = f"https://{base_url}:{port}"
            else:
                base_url = PING_URL.split(':')[0]
                PING_URL = f"http://{base_url}:{port}"
            logger.info(f"Updated PING_URL to {PING_URL}")
        
        server = HTTPServer(('0.0.0.0', port), PingHandler)
        logger.info(f"Server started on port {port}")
        server.serve_forever()
    
    Thread(target=server_thread, daemon=True).start()

async def main():
    # Initialize persistence using PicklePersistence
    persistence = PicklePersistence(filepath=PERSISTENCE_FILE)
    
    # Create bot application with persistence (without rate limiting)
    app = ApplicationBuilder() \
        .token(BOT_TOKEN) \
        .persistence(persistence) \
        .build()

    # Add command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("coin", coin_command))
    app.add_handler(CommandHandler("add", add_alert))
    app.add_handler(CommandHandler("list", list_alerts))
    app.add_handler(CommandHandler("remove", remove_alert))
    app.add_handler(CommandHandler("price", get_price))
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    # Start ping server
    run_ping_server()
    
    # Setup price checking job
    app.job_queue.run_repeating(check_prices, interval=15, first=5)
    logger.info("Price check job scheduled every 15 seconds")
    
    # Start self-pinging
    asyncio.create_task(ping_self())

    # Start the bot
    logger.info("Bot is starting...")
    await app.run_polling()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")