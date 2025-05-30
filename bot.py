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

# Configuration
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set!")

PING_URL = os.getenv("PING_URL")
ALLOWED_USERS = {5817239686, 5274796002}

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

# ===== COMMAND HANDLERS =====

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ALLOWED_USERS:
        await update.message.reply_text("❌ Sorry, you are not authorized to use this bot.")
        return
    
    await update.message.reply_text(
        "👋 Welcome to Crypto Alert Bot!\n\n"
        "Use /add COIN PRICE [above|below] to set price alerts.\n"
        "Example: /add btc 50000 below\n\n"
        "Use /help for all commands."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ALLOWED_USERS:
        return
    
    help_text = """
📌 Available Commands:
/start - Start the bot
/help - Show this help
/add COIN PRICE [above|below] - Set price alert
/list - List your alerts
/remove INDEX - Remove an alert
/price COIN - Check current price
Example: /price btc
"""
    await update.message.reply_text(help_text)

async def add_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ALLOWED_USERS:
        return

    if len(context.args) < 2:
        await update.message.reply_text("Usage: /add COIN PRICE [above|below]")
        return

    symbol = context.args[0].lower()
    if symbol not in SYMBOL_MAP:
        await update.message.reply_text(f"❌ Unknown coin: {symbol}")
        return

    try:
        price = float(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Invalid price format")
        return

    direction = "above"
    if len(context.args) > 2 and context.args[2].lower() == "below":
        direction = "below"

    alerts = load_alerts()
    user_alerts = alerts.get(str(user_id), [])
    user_alerts.append({
        "coin": SYMBOL_MAP[symbol],
        "symbol": symbol,
        "price": price,
        "direction": direction
    })
    alerts[str(user_id)] = user_alerts
    save_alerts(alerts)

    await update.message.reply_text(
        f"✅ Alert set for {symbol.upper()} ${price} ({direction})"
    )

async def list_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ALLOWED_USERS:
        return

    alerts = load_alerts().get(str(user_id), [])
    if not alerts:
        await update.message.reply_text("You have no active alerts.")
        return

    message = "📋 Your alerts:\n"
    for i, alert in enumerate(alerts, 1):
        message += f"{i}. {alert['symbol'].upper()} {alert['direction']} ${alert['price']}\n"
    
    await update.message.reply_text(message)

async def remove_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ALLOWED_USERS:
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /remove INDEX")
        return

    index = int(context.args[0]) - 1
    alerts = load_alerts()
    user_alerts = alerts.get(str(user_id), [])

    if index < 0 or index >= len(user_alerts):
        await update.message.reply_text("❌ Invalid alert index")
        return

    removed = user_alerts.pop(index)
    if user_alerts:
        alerts[str(user_id)] = user_alerts
    else:
        alerts.pop(str(user_id))
    save_alerts(alerts)

    await update.message.reply_text(
        f"✅ Removed alert for {removed['symbol'].upper()} ${removed['price']}"
    )

async def get_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /price COIN")
        return

    symbol = context.args[0].lower()
    if symbol not in SYMBOL_MAP:
        await update.message.reply_text(f"❌ Unknown coin: {symbol}")
        return

    try:
        response = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": SYMBOL_MAP[symbol], "vs_currencies": "usd"},
            timeout=10
        )
        response.raise_for_status()
        price = response.json()[SYMBOL_MAP[symbol]]["usd"]
        await update.message.reply_text(f"💰 {symbol.upper()}: ${price:,.4f}")
    except Exception as e:
        logger.error(f"Price check failed: {e}")
        await update.message.reply_text("❌ Failed to fetch price")

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Unknown command. Use /help for available commands.")

# ===== PRICE CHECKING JOB =====

async def check_prices(context: ContextTypes.DEFAULT_TYPE):
    try:
        alerts = load_alerts()
        if not alerts:
            return

        # Get unique coins to check
        coins = list({alert['coin'] for user_alerts in alerts.values() for alert in user_alerts})
        
        # Fetch current prices
        response = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": ",".join(coins), "vs_currencies": "usd"},
            timeout=15
        )
        response.raise_for_status()
        prices = response.json()

        # Check alerts
        for user_id, user_alerts in list(alerts.items()):
            to_remove = []
            for i, alert in enumerate(user_alerts):
                current_price = prices.get(alert["coin"], {}).get("usd")
                if current_price is None:
                    continue

                triggered = False
                if alert["direction"] == "above" and current_price >= alert["price"]:
                    triggered = True
                elif alert["direction"] == "below" and current_price <= alert["price"]:
                    triggered = True

                if triggered:
                    try:
                        await context.bot.send_message(
                            chat_id=int(user_id),
                            text=f"🚨 {alert['symbol'].upper()} is now ${current_price:,.4f} ({alert['direction']} ${alert['price']})"
                        )
                        to_remove.append(i)
                    except Exception as e:
                        logger.error(f"Failed to send alert: {e}")

            # Remove triggered alerts
            for i in sorted(to_remove, reverse=True):
                user_alerts.pop(i)

            # Update alerts
            if user_alerts:
                alerts[str(user_id)] = user_alerts
            else:
                alerts.pop(str(user_id))

        save_alerts(alerts)

    except Exception as e:
        logger.error(f"Price check job failed: {e}")

# ===== SERVER & PING =====

class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Pong")

def find_available_port(start_port=10001, max_attempts=20):
    for port in range(start_port, start_port + max_attempts):
        try:
            with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
                s.bind(('0.0.0.0', port))
                return port
        except socket.error:
            continue
    raise RuntimeError(f"No available ports found between {start_port}-{start_port + max_attempts - 1}")

def run_ping_server():
    def server_thread():
        port = find_available_port()
        logger.info(f"Starting ping server on port {port}")
        
        global PING_URL
        if PING_URL:
            if PING_URL.startswith('http'):
                base_url = PING_URL.split('://')[1].split(':')[0]
                protocol = PING_URL.split('://')[0]
                PING_URL = f"{protocol}://{base_url}:{port}"
            else:
                base_url = PING_URL.split(':')[0]
                PING_URL = f"http://{base_url}:{port}"
            logger.info(f"Updated PING_URL: {PING_URL}")
        
        server = HTTPServer(('0.0.0.0', port), PingHandler)
        logger.info("Ping server ready")
        server.serve_forever()
    
    Thread(target=server_thread, daemon=True).start()

async def ping_self():
    if not PING_URL:
        logger.info("PING_URL not set, skipping self-pinging")
        return
    
    logger.info(f"Starting self-pinging to {PING_URL}")
    while True:
        try:
            requests.get(PING_URL, timeout=10)
            logger.debug("Ping successful")
        except Exception as e:
            logger.warning(f"Ping failed: {e}")
        await asyncio.sleep(300)  # 5 minutes

# ===== MAIN =====

async def main():
    # Initialize persistence
    persistence = PicklePersistence(filepath=PERSISTENCE_FILE)
    
    # Create bot application
    app = ApplicationBuilder() \
        .token(BOT_TOKEN) \
        .persistence(persistence) \
        .build()

    # Add command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("add", add_alert))
    app.add_handler(CommandHandler("list", list_alerts))
    app.add_handler(CommandHandler("remove", remove_alert))
    app.add_handler(CommandHandler("price", get_price))
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    # Schedule price checking job
    app.job_queue.run_repeating(check_prices, interval=15, first=5)
    
    # Start ping server and self-pinging
    run_ping_server()
    asyncio.create_task(ping_self())

    # Start the bot
    logger.info("Bot starting...")
    await app.run_polling()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")