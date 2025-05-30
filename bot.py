import os
import asyncio
import requests
from dotenv import load_dotenv
from threading import Thread
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters
)
from tinydb import TinyDB, Query

# Load environment variables
load_dotenv()

# Environment Config
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PING_URL = os.getenv("PING_URL")

# Allowed users
ALLOWED_USERS = {5817239686, 5274796002}

# Coin symbol map
SYMBOL_MAP = {
    "btc": "bitcoin", "eth": "ethereum", "bnb": "binancecoin",
    "sol": "solana", "ada": "cardano", "doge": "dogecoin",
    "xrp": "ripple", "meme": "meme", "moxie": "moxie", "degen": "degen-base"
}

# Persistent DB (Mount persistent disk at /data on Render)
os.makedirs("/data", exist_ok=True)
db = TinyDB('/data/prices.json')

# ======================= Commands =======================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ALLOWED_USERS:
        return await update.message.reply_text("❌ You are not authorized.")
    await update.message.reply_text(
        "👋 Welcome to Crypto Alert Bot!\n\n"
        "Use <b>/add COIN PRICE</b> or <b>/add COIN PRICE below</b>\n"
        "Example: /add BTC 100000\n", parse_mode="HTML"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ALLOWED_USERS:
        return await update.message.reply_text("❌ Unauthorized.")
    await update.message.reply_text(
        "/start - Start the bot\n"
        "/add COIN PRICE [above|below] - Set alert\n"
        "/list - List alerts\n"
        "/remove NUMBER - Remove alert\n"
        "/coin - Show available coins\n"
        "/price COIN [COIN2 ...] - Get current prices\n"
        "/help - Show help\n", parse_mode="HTML"
    )

async def coin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ALLOWED_USERS:
        return await update.message.reply_text("❌ Unauthorized.")
    coins = "\n".join([f"• {k.upper()} ({v})" for k, v in SYMBOL_MAP.items()])
    await update.message.reply_text(f"<b>📊 Coins:</b>\n{coins}", parse_mode="HTML")

async def add_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if int(user_id) not in ALLOWED_USERS:
        return await update.message.reply_text("❌ Unauthorized.")

    if len(context.args) < 2:
        return await update.message.reply_text("❗ Usage: /add COIN PRICE [above|below]")

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

    db.insert({"user_id": user_id, "coin": coin, "symbol": symbol, "price": price, "direction": direction})
    await update.message.reply_text(f"✅ Alert set for {symbol.upper()} ${price} ({direction})")

async def list_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if int(user_id) not in ALLOWED_USERS:
        return await update.message.reply_text("❌ Unauthorized.")

    alerts = db.search(Query().user_id == user_id)
    if not alerts:
        return await update.message.reply_text("You have no active alerts.")

    msg = "📋 Your alerts:\n"
    for i, alert in enumerate(alerts, 1):
        msg += f"{i}. {alert['symbol'].upper()} {alert['direction']} ${alert['price']}\n"
    await update.message.reply_text(msg)

async def remove_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if int(user_id) not in ALLOWED_USERS:
        return await update.message.reply_text("❌ Unauthorized.")

    if len(context.args) != 1 or not context.args[0].isdigit():
        return await update.message.reply_text("❗ Usage: /remove NUMBER")

    index = int(context.args[0]) - 1
    alerts = db.search(Query().user_id == user_id)

    if index < 0 or index >= len(alerts):
        return await update.message.reply_text("❗ Invalid alert number.")

    removed = alerts[index]
    db.remove(doc_ids=[alerts[index].doc_id])
    await update.message.reply_text(
        f"✅ Removed alert for {removed['symbol'].upper()} ${removed['price']} ({removed['direction']})"
    )

async def get_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ALLOWED_USERS:
        return await update.message.reply_text("❌ Unauthorized.")
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
            lines.append(f"💰 {s.upper()}: ${price:.5f}" if price else f"⚠️ {s.upper()}: Price not found")
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text("⚠️ Failed to fetch prices.")

# =============== Price Check Job ===============
async def check_prices(context: ContextTypes.DEFAULT_TYPE):
    alerts = db.all()
    if not alerts:
        return
    coins = list({alert["coin"] for alert in alerts})
    try:
        prices = requests.get("https://api.coingecko.com/api/v3/simple/price",
                              params={"ids": ",".join(coins), "vs_currencies": "usd"}).json()
    except Exception as e:
        print("Price fetch failed", e)
        return

    for alert in alerts:
        user_id = alert["user_id"]
        coin = alert["coin"]
        current = prices.get(coin, {}).get("usd")
        if current is None:
            continue

        hit = (alert["direction"] == "above" and current >= alert["price"]) or \
              (alert["direction"] == "below" and current <= alert["price"])
        if hit:
            await context.bot.send_message(
                chat_id=int(user_id),
                text=f"🚨 {alert['symbol'].upper()} is ${current:.5f}, hit {alert['direction']} ${alert['price']}!"
            )
            db.remove(doc_ids=[alert.doc_id])

# =============== Ping Server ===============
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

async def ping_self():
    while True:
        try:
            if PING_URL:
                requests.get(PING_URL)
                print("🔁 Pinged self")
        except:
            pass
        await asyncio.sleep(300)

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Unknown command. Use /help")

# =============== Main App ===============
async def main():
    run_ping_server()
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

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    asyncio.run(main())
