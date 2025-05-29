import json
import os
import requests
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

ALERT_FILE = 'prices.json'

def load_alerts():
    if os.path.exists(ALERT_FILE):
        with open(ALERT_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_alerts(data):
    with open(ALERT_FILE, 'w') as f:
        json.dump(data, f, indent=2)

# Telegram Bot Token
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    print("❌ Error: TELEGRAM_BOT_TOKEN environment variable not set.")
    exit(1)

# Allowed users
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ALLOWED_USERS:
        return await update.message.reply_text("❌ Sorry, you are not authorized to use this bot.")
    await update.message.reply_text(
        "👋 Welcome to Crypto Alert Bot!\n\n"
        "Use <b>/add COIN PRICE [above|below]</b> to set an alert.\n"
        "Example: <b>/add BTC 100000</b> or <b>/add BTC 100000 below</b>\n"
        "Use <b>/help</b> to see more commands.",
        parse_mode="HTML"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ALLOWED_USERS:
        return await update.message.reply_text("❌ Not authorized.")
    await update.message.reply_text(
        "📌 <b>Commands:</b>\n"
        "/start - Start the bot\n"
        "/add COIN PRICE [above|below] - Set a price alert\n"
        "/list - Show active alerts\n"
        "/remove NUMBER - Remove an alert\n"
        "/coin - Show supported coins\n"
        "/price COIN1 COIN2 ... - Check current prices\n"
        "/help - Show help",
        parse_mode="HTML"
    )

async def coin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ALLOWED_USERS:
        return await update.message.reply_text("❌ Not authorized.")
    coin_list = "\n".join([f"• {k.upper()} ({v})" for k, v in SYMBOL_MAP.items()])
    await update.message.reply_text(
        f"📊 <b>Available Coins:</b>\n{coin_list}",
        parse_mode="HTML"
    )

async def add_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ALLOWED_USERS:
        return await update.message.reply_text("❌ Not authorized.")

    if len(context.args) < 2:
        return await update.message.reply_text("❗ Usage: /add COIN PRICE [above|below]", parse_mode="HTML")

    symbol = context.args[0].lower()
    coin = SYMBOL_MAP.get(symbol)
    if not coin:
        return await update.message.reply_text("❗ Unsupported coin.")

    try:
        price = float(context.args[1])
    except ValueError:
        return await update.message.reply_text("❗ Invalid price.")

    direction = "above"
    if len(context.args) == 3 and context.args[2].lower() in ["above", "below"]:
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

    await update.message.reply_text(f"✅ Alert set for {symbol.upper()} at ${price} ({direction}).")

async def list_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ALLOWED_USERS:
        return await update.message.reply_text("❌ Not authorized.")

    alerts = load_alerts()
    user_alerts = alerts.get(str(user_id), [])
    if not user_alerts:
        return await update.message.reply_text("📭 No active alerts.")
    
    lines = [f"{idx + 1}. {a['symbol'].upper()} {a['direction']} ${a['price']}" for idx, a in enumerate(user_alerts)]
    await update.message.reply_text("📋 <b>Your alerts:</b>\n" + "\n".join(lines), parse_mode="HTML")

async def remove_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ALLOWED_USERS:
        return await update.message.reply_text("❌ Not authorized.")
    if not context.args:
        return await update.message.reply_text("❗ Usage: /remove ALERT_NUMBER")

    try:
        idx = int(context.args[0]) - 1
    except ValueError:
        return await update.message.reply_text("❗ Invalid alert number.")

    alerts = load_alerts()
    user_alerts = alerts.get(str(user_id), [])

    if idx < 0 or idx >= len(user_alerts):
        return await update.message.reply_text("❗ Alert number out of range.")

    removed = user_alerts.pop(idx)
    if user_alerts:
        alerts[str(user_id)] = user_alerts
    else:
        alerts.pop(str(user_id), None)

    save_alerts(alerts)
    await update.message.reply_text(f"✅ Removed alert for {removed['symbol'].upper()} ${removed['price']} ({removed['direction']})")

async def get_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ALLOWED_USERS:
        return await update.message.reply_text("❌ Not authorized.")

    if not context.args:
        return await update.message.reply_text("❗ Usage: /price COIN1 COIN2", parse_mode="HTML")

    symbols = [arg.lower() for arg in context.args]
    unknown = [s for s in symbols if s not in SYMBOL_MAP]
    if unknown:
        return await update.message.reply_text(f"❗ Unsupported coin(s): {', '.join(unknown)}")

    ids = [SYMBOL_MAP[s] for s in symbols]
    url = "https://api.coingecko.com/api/v3/simple/price"

    try:
        res = requests.get(url, params={"ids": ",".join(ids), "vs_currencies": "usd"})
        data = res.json()
        lines = [f"💰 {s.upper()}: ${data[SYMBOL_MAP[s]]['usd']:.5f}" for s in symbols]
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        print("⚠️ Error fetching prices:", e)
        await update.message.reply_text("⚠️ Failed to fetch prices.")

async def check_prices(context: ContextTypes.DEFAULT_TYPE):
    alerts = load_alerts()
    if not alerts:
        return

    coins = list({alert['coin'] for user_alerts in alerts.values() for alert in user_alerts})
    url = "https://api.coingecko.com/api/v3/simple/price"

    try:
        res = requests.get(url, params={"ids": ','.join(coins), "vs_currencies": "usd"}).json()
    except Exception as e:
        print("⚠️ Error fetching prices:", e)
        return

    for user_id, user_alerts in list(alerts.items()):
        updated_alerts = []
        for alert in user_alerts:
            coin = alert['coin']
            current = res.get(coin, {}).get('usd')
            if current is None:
                continue

            if (alert['direction'] == 'above' and current >= alert['price']) or \
               (alert['direction'] == 'below' and current <= alert['price']):
                await context.bot.send_message(
                    chat_id=int(user_id),
                    text=f"🚨 {alert['symbol'].upper()} is ${current:.5f} (Target {alert['direction']} ${alert['price']})"
                )
            else:
                updated_alerts.append(alert)

        if updated_alerts:
            alerts[user_id] = updated_alerts
        else:
            alerts.pop(user_id)

    save_alerts(alerts)

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Unknown command. Type /help for available options.", parse_mode="HTML")

async def main():
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

    print("🤖 Bot is running...")
    await app.run_polling()

if __name__ == "__main__":
    import asyncio
    try:
        asyncio.run(main())
    except RuntimeError:
        import nest_asyncio
        nest_asyncio.apply()
        asyncio.run(main())
