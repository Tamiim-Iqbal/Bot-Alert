import json
import os
import requests
import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    Defaults,
    Persistence
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

# === BOT COMMANDS ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ALLOWED_USERS:
        await update.message.reply_text("❌ Sorry, you are not authorized to use this bot.")
        logger.warning(f"Unauthorized access attempt by user {user_id}")
        return
    
    await update.message.reply_text(
        "👋 Welcome to Crypto Alert Bot!\n\n"
        "Use <b><i>/add COIN PRICE</i></b> or <b><i>/add COIN PRICE below</i></b> - to set a price alert.\n\n"
        "Examples:\n"
        "<b><i>/add BTC 100000</i></b>\n"
        "<b><i>/add BTC 100000 below</i></b>\n\n"
        "Use <b><i>/help</i></b> for all commands.",
        parse_mode="HTML"
    )
    logger.info(f"User {user_id} started the bot")

# [Keep all your existing command functions (help_command, coin_command, etc.) 
# but add similar error handling and logging as shown in start()]

async def get_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ALLOWED_USERS:
        await update.message.reply_text("❌ You are not authorized.")
        return
    
    if not context.args:
        await update.message.reply_text("❗ Usage: /price COIN [COIN2 ...]")
        return

    symbols = [s.lower() for s in context.args]
    unknown = [s for s in symbols if s not in SYMBOL_MAP]
    if unknown:
        await update.message.reply_text(f"❗ Unknown coin(s): {', '.join(unknown)}")
        return

    ids = [SYMBOL_MAP[s] for s in symbols]
    try:
        res = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": ",".join(ids), "vs_currencies": "usd"},
            timeout=10
        )
        res.raise_for_status()
        price_data = res.json()
        
        lines = []
        for s in symbols:
            coin_id = SYMBOL_MAP[s]
            price = price_data.get(coin_id, {}).get("usd")
            if price is not None:
                lines.append(f"💰 {s.upper()}: ${price:.5f}")
            else:
                lines.append(f"⚠️ {s.upper()}: Price not found")
        
        await update.message.reply_text("\n".join(lines))
        logger.info(f"User {user_id} checked prices for {', '.join(symbols)}")
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Price check failed for user {user_id}: {e}")
        await update.message.reply_text("⚠️ Failed to fetch prices. Please try again later.")
    except Exception as e:
        logger.error(f"Unexpected error in get_price: {e}")
        await update.message.reply_text("⚠️ An error occurred. Please try again.")

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

# ========== SELF-PINGING ==========
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

# ========== SIMPLE SERVER ==========
class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Pong")
        logger.debug("Received ping request")

def run_ping_server():
    def server_thread():
        logger.info("Starting ping server on port 10001")
        server = HTTPServer(('0.0.0.0', 10001), PingHandler)
        server.serve_forever()
    Thread(target=server_thread, daemon=True).start()

# ========== MAIN ==========
async def main():
    # Initialize persistence
    persistence = Persistence(filename=PERSISTENCE_FILE)
    
    # Create bot application with persistence and rate limiting
    app = ApplicationBuilder() \
        .token(BOT_TOKEN) \
        .persistence(persistence) \
        .defaults(Defaults(rate_limit=30)) \
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
    app.job_queue.scheduler.add_job(
        check_prices,
        'interval',
        seconds=15,
        id='price_check',
        replace_existing=True
    )
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