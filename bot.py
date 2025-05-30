import json
import os
import requests
import asyncio
import nest_asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# File to store alerts
ALERT_FILE = 'prices.json'

def load_alerts():
    if os.path.exists(ALERT_FILE):
        with open(ALERT_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_alerts(data):
    with open(ALERT_FILE, 'w') as f:
        json.dump(data, f, indent=2)

# Your Telegram bot token and ping URL
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PING_URL = os.getenv("PING_URL")  # Example: "https://your-app-url.onrailway.app"

# Allowed users
ALLOWED_USERS = {5817239686, 5274796002}

# Symbol to CoinGecko ID map
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

# Commands

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ALLOWED_USERS:
        return await update.message.reply_text("❌ Sorry, you are not authorized to use this bot.")
    await update.message.reply_text(
        "👋 Welcome to Crypto Alert Bot!\n\n"
        "Use <b><i>/add COIN PRICE</i></b> or <b><i>/add COIN PRICE below</i></b> - to set a price alert.\n\n"
        "Examples:\n"
        "<b><i>/add BTC 100000</i></b>\n"
        "<b><i>/add BTC 100000 below</i></b>\n\n"
        "Use <b><i>/help</i></b> for all commands.",
        parse_mode="HTML"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ALLOWED_USERS:
        return await update.message.reply_text("❌ You are not authorized.")
    await update.message.reply_text(
        "📌 Commands:\n"
        "/start - Start the bot\n"
        "/add COIN PRICE [above|below] - Set alert\n"
        "/list - List alerts\n"
        "/remove NUMBER - Remove alert\n"
        "/coin - Show available coins\n"
        "/price COIN [COIN2 ...] - Get current prices\n"
        "/help - Show this help\n",
        parse_mode="HTML"
    )

async def coin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ALLOWED_USERS:
        return await update.message.reply_text("❌ You are not authorized.")
    coins = "\n".join([f"• {k.upper()} ({v})" for k, v in SYMBOL_MAP.items()])
    await update.message.reply_text(
        f"<b>📊 Coins:</b>\n{coins}\n\n"
        "Use /add COIN PRICE [above|below] to set an alert.\n"
        "Example: /add btc 50000 below\n",
        parse_mode="HTML"
    )

async def add_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ALLOWED_USERS:
        return await update.message.reply_text("❌ You are not authorized.")

    if len(context.args) < 2:
        return await update.message.reply_text(
            "❗ Usage: /add COIN PRICE [above|below]\nExample: /add btc 30000 below",
            parse_mode="HTML"
        )

    symbol = context.args[0].lower()
    coin = SYMBOL_MAP.get(symbol)
    if not coin:
        return await update.message.reply_text("❗ Unsupported coin.")

    try:
        price = float(context.args[1])
    except ValueError:
        return await update.message.reply_text("❗ Invalid price.")

    direction = "above"
    if len(context.args) >= 3 and context.args[2].lower() in ["above", "below"]:
        direction = context.args[2].lower()

    alerts = load_alerts()
    user_alerts = alerts.get(str(user_id), [])
    user_alerts.append({
        "coin": coin,
        "symbol": symbol,
        "price": price,
        "direction": direction
    })
    alerts[str(user_id)] = user_alerts
    save_alerts(alerts)

    await update.message.reply_text(f"✅ Alert set for {symbol.upper()} ${price} ({direction})")

async def list_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ALLOWED_USERS:
        return await update.message.reply_text("❌ You are not authorized.")
    alerts = load_alerts()
    user_alerts = alerts.get(str(user_id), [])

    if not user_alerts:
        return await update.message.reply_text("You have no active alerts.")

    msg = "📋 Your alerts:\n"
    for i, alert in enumerate(user_alerts, start=1):
        msg += f"{i}. {alert['symbol'].upper()} {alert['direction']} ${alert['price']}\n"
    await update.message.reply_text(msg)

async def remove_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ALLOWED_USERS:
        return await update.message.reply_text("❌ You are not authorized.")

    if len(context.args) != 1 or not context.args[0].isdigit():
        return await update.message.reply_text("❗ Usage: /remove ALERT_NUMBER")

    idx = int(context.args[0]) - 1
    alerts = load_alerts()
    user_alerts = alerts.get(str(user_id), [])

    if idx < 0 or idx >= len(user_alerts):
        return await update.message.reply_text("❗ Invalid alert number.")

    removed = user_alerts.pop(idx)
    if user_alerts:
        alerts[str(user_id)] = user_alerts
    else:
        alerts.pop(str(user_id))
    save_alerts(alerts)
    await update.message.reply_text(
        f"✅ Removed alert for {removed['symbol'].upper()} ${removed['price']} ({removed['direction']})"
    )

async def get_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ALLOWED_USERS:
        return await update.message.reply_text("❌ You are not authorized.")
    if not context.args:
        return await update.message.reply_text("❗ Usage: /price COIN [COIN2 ...]")

    symbols = [s.lower() for s in context.args]
    unknown = [s for s in symbols if s not in SYMBOL_MAP]
    if unknown:
        return await update.message.reply_text(f"❗ Unknown coin(s): {', '.join(unknown)}")

    ids = [SYMBOL_MAP[s] for s in symbols]
    try:
        res = requests.get("https://api.coingecko.com/api/v3/simple/price",
                           params={"ids": ",".join(ids), "vs_currencies": "usd"}).json()
        lines = []
        for s in symbols:
            price = res.get(SYMBOL_MAP[s], {}).get("usd")
            if price is not None:
                lines.append(f"💰 {s.upper()}: ${price:.5f}")
            else:
                lines.append(f"⚠️ {s.upper()}: Price not found")
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        print("Error fetching prices:", e)
        await update.message.reply_text("⚠️ Failed to fetch prices.")

async def check_prices(context: ContextTypes.DEFAULT_TYPE):
    alerts = load_alerts()
    if not alerts:
        return

    coins = list({alert['coin'] for alerts in alerts.values() for alert in alerts})
    try:
        prices = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": ",".join(coins), "vs_currencies": "usd"}
        ).json()
    except Exception as e:
        print("Error fetching prices:", e)
        return

    for user_id, user_alerts in list(alerts.items()):
        to_remove = []
        for i, alert in enumerate(user_alerts):
            current = prices.get(alert["coin"], {}).get("usd")
            if current is None:
                continue
            if (alert["direction"] == "above" and current >= alert["price"]) or \
               (alert["direction"] == "below" and current <= alert["price"]):
                await context.bot.send_message(
                    chat_id=int(user_id),
                    text=f"🚨 {alert['symbol'].upper()} is ${current:.5f}, hit {alert['direction']} ${alert['price']}!"
                )
                to_remove.append(i)
        for i in reversed(to_remove):
            user_alerts.pop(i)
        if user_alerts:
            alerts[user_id] = user_alerts
        else:
            alerts.pop(user_id)
    save_alerts(alerts)

# ========== SELF-PINGING ==========
async def ping_self():
    while True:
        try:
            if PING_URL:
                requests.get(PING_URL)
                print("🔁 Pinged self")
        except Exception as e:
            print("Ping failed", e)
        await asyncio.sleep(300)  # every 5 minutes

# ========== SIMPLE SERVER ==========
class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Pong")

def run_ping_server():
    def server_thread():
        server = HTTPServer(('0.0.0.0', 10001), PingHandler)
        server.serve_forever()
    Thread(target=server_thread, daemon=True).start()

# Unknown command
async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Unknown command. Use /help for help.")

# Main function
async def main():
    run_ping_server()  # Start the ping server in a separate thread
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("coin", coin_command))
    app.add_handler(CommandHandler("add", add_alert))
    app.add_handler(CommandHandler("list", list_alerts))
    app.add_handler(CommandHandler("remove", remove_alert))
    app.add_handler(CommandHandler("price", get_price))
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    app.job_queue.run_repeating(check_prices, interval=15, first=5)
    asyncio.create_task(ping_self())

    print("🤖 Bot is running...")
    await app.run_polling()

# if __name__ == "__main__":
#     import asyncio
#     try:
#         asyncio.run(main())
#     except RuntimeError:
#         import nest_asyncio
#         nest_asyncio.apply()
#         asyncio.run(main())
if __name__ == "__main__":
    import asyncio
    import nest_asyncio

    try:
        asyncio.run(main())
    except RuntimeError as e:
        if "event loop is already running" in str(e):
            nest_asyncio.apply()
            loop = asyncio.get_event_loop()
            loop.run_until_complete(main())
        else:
            raise
