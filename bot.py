import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

import json
import pyotp
import time
import logging
import os
import requests
from datetime import datetime
from growwapi import GrowwAPI

# ── Logging setup ─────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    handlers=[
        logging.FileHandler("bot_log.txt"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger()

# ── Auto-load credentials from .env ──────────────────────
def load_env():
    if os.path.exists(".env"):
        with open(".env") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip()

load_env()

TOTP_TOKEN         = os.environ.get("GROWW_TOTP_TOKEN")
TOTP_SECRET        = os.environ.get("GROWW_TOTP_SECRET")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID")

# ── Telegram alert ────────────────────────────────────────
def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message})
    except Exception as e:
        log.error(f"Telegram error: {e}")

# ── Connect ───────────────────────────────────────────────
totp         = pyotp.TOTP(TOTP_SECRET).now()
access_token = GrowwAPI.get_access_token(api_key=TOTP_TOKEN, totp=totp)
client       = GrowwAPI(access_token)
log.info("Connected! Multi-stock bot is running...")
send_telegram("🤖 Multi-stock bot started!\nWatching: INFY, RELIANCE, TCS, HDFCBANK, ICICIBANK")

# ── Stock config ──────────────────────────────────────────
# Each stock has its own settings
STOCKS = {
    "INFY":      {"quantity": 1, "buy_pct": 0.99, "sell_pct": 1.01, "stop_pct": 0.97},
    "RELIANCE":  {"quantity": 1, "buy_pct": 0.99, "sell_pct": 1.01, "stop_pct": 0.97},
    "TCS":       {"quantity": 1, "buy_pct": 0.99, "sell_pct": 1.01, "stop_pct": 0.97},
    "HDFCBANK":  {"quantity": 1, "buy_pct": 0.99, "sell_pct": 1.01, "stop_pct": 0.97},
    "ICICIBANK": {"quantity": 1, "buy_pct": 0.99, "sell_pct": 1.01, "stop_pct": 0.97},
}

# ── Market hours check ────────────────────────────────────
def is_market_open():
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    market_open  = now.replace(hour=9,  minute=15, second=0)
    market_close = now.replace(hour=15, minute=30, second=0)
    return market_open <= now <= market_close

# ── Signal logic ──────────────────────────────────────────
def get_signal(price, buy_target, sell_target, stop_loss):
    if price <= stop_loss:
        return "STOP_LOSS"
    elif price <= buy_target:
        return "BUY"
    elif price >= sell_target:
        return "SELL"
    else:
        return "HOLD"

# ── Place order ───────────────────────────────────────────
import json
from datetime import datetime

TRADES_FILE = "trades.json"

def load_trades():
    if os.path.exists(TRADES_FILE):
        with open(TRADES_FILE) as f:
            return json.load(f)
    return []

def save_trade(symbol, action, price, quantity):
    trades = load_trades()
    trades.append({
        "symbol":    symbol,
        "action":    action,
        "price":     price,
        "quantity":  quantity,
        "time":      datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "pnl":       None
    })
    # Calculate P&L if this is a SELL
    if action in ("SELL", "STOP_LOSS"):
        # Find the last BUY for this symbol
        for t in reversed(trades[:-1]):
            if t["symbol"] == symbol and t["action"] == "BUY" and t["pnl"] is None:
                pnl = round((price - t["price"]) * quantity, 2)
                trades[-1]["pnl"] = pnl
                t["pnl"] = "closed"
                break
    with open(TRADES_FILE, "w") as f:
        json.dump(trades, f, indent=2)

# ── Place order helper ────────────────────────────────────
def place_order(symbol, transaction_type, price, quantity):
    order = client.place_order(
        trading_symbol=symbol,
        quantity=quantity,
        validity=client.VALIDITY_DAY,
        exchange=client.EXCHANGE_NSE,
        segment=client.SEGMENT_CASH,
        product=client.PRODUCT_CNC,
        order_type=client.ORDER_TYPE_LIMIT,
        transaction_type=transaction_type,
        price=price
    )
    action = "BUY" if transaction_type == client.TRANSACTION_TYPE_BUY else "SELL"
    save_trade(symbol, action, price, quantity)
    return order
# ── Process one stock ─────────────────────────────────────
def process_stock(symbol, config):
    try:
        # Fetch live price
        ltp_data = client.get_ltp(
            segment=client.SEGMENT_CASH,
            exchange_trading_symbols=f"NSE_{symbol}"
        )
        price = ltp_data[f"NSE_{symbol}"]

        # Calculate targets
        buy_target  = round(price * config["buy_pct"],  1)
        sell_target = round(price * config["sell_pct"], 1)
        stop_loss   = round(price * config["stop_pct"], 1)
        quantity    = config["quantity"]

        # Get signal
        signal = get_signal(price, buy_target, sell_target, stop_loss)
        log.info(f"{symbol} ₹{price} | Signal: {signal}")

        # Act on signal
        if signal == "BUY":
            order = place_order(symbol, client.TRANSACTION_TYPE_BUY, buy_target, quantity)
            msg = f"✅ BUY {symbol}\nPrice: ₹{price}\nOrder @ ₹{buy_target}"
            log.info(msg)
            send_telegram(msg)

        elif signal == "SELL":
            order = place_order(symbol, client.TRANSACTION_TYPE_SELL, sell_target, quantity)
            msg = f"💰 SELL {symbol}\nPrice: ₹{price}\nOrder @ ₹{sell_target}"
            log.info(msg)
            send_telegram(msg)

        elif signal == "STOP_LOSS":
            order = place_order(symbol, client.TRANSACTION_TYPE_SELL, sell_target, quantity)
            msg = f"🛑 STOP LOSS {symbol}\nPrice: ₹{price}\nOrder @ ₹{sell_target}"
            log.info(msg)
            send_telegram(msg)

    except Exception as e:
        log.error(f"❌ Error processing {symbol}: {e}")

# ── Main loop ─────────────────────────────────────────────
while True:
    try:
#        if not is_market_open():
 #           log.info("Market is closed. Waiting 5 minutes...")
 #           time.sleep(300)
  #          continue

        log.info("── Scanning all stocks ──────────────────")
        for symbol, config in STOCKS.items():
            process_stock(symbol, config)
            time.sleep(1)  # 1 second gap between each stock
        log.info("── Scan complete. Next in 5 minutes ────")

    except Exception as e:
        log.error(f"❌ Bot error: {e}")
        send_telegram(f"❌ Bot Error: {e}")

    time.sleep(300)