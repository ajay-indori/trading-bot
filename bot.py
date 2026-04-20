import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

import json
import pyotp
import time
import logging
import os
import requests
from datetime import datetime, timedelta
from growwapi import GrowwAPI
from news_trigger import check_news_trigger          # ← NEW

# ── Logging setup ─────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    handlers=[
        logging.FileHandler("bot_log.txt", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
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

# ── Connect to Groww ──────────────────────────────────────
totp         = pyotp.TOTP(TOTP_SECRET).now()
access_token = GrowwAPI.get_access_token(api_key=TOTP_TOKEN, totp=totp)
client       = GrowwAPI(access_token)
log.info("Connected! Bot is running...")

# ── Settings ──────────────────────────────────────────────
STOP_PCT    = 0.97
TRADES_FILE = "trades.json"
LEVELS_FILE = "levels.json"

# ── Load levels from levels.json ──────────────────────────
def load_levels():
    if os.path.exists(LEVELS_FILE):
        with open(LEVELS_FILE) as f:
            return json.load(f)
    return {}

# ── Market hours check ────────────────────────────────────
def is_market_open():
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    market_open  = now.replace(hour=9,  minute=15, second=0)
    market_close = now.replace(hour=15, minute=30, second=0)
    return market_open <= now <= market_close

# ── P&L tracking ─────────────────────────────────────────
def load_trades():
    if os.path.exists(TRADES_FILE):
        with open(TRADES_FILE) as f:
            return json.load(f)
    return []

def save_trade(symbol, action, price, quantity):
    trades = load_trades()
    trades.append({
        "symbol":   symbol,
        "action":   action,
        "price":    price,
        "quantity": quantity,
        "time":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "pnl":      None
    })
    if action in ("SELL", "STOP_LOSS"):
        for t in reversed(trades[:-1]):
            if t["symbol"] == symbol and t["action"] == "BUY" and t["pnl"] is None:
                pnl = round((price - t["price"]) * quantity, 2)
                trades[-1]["pnl"] = pnl
                t["pnl"] = "closed"
                break
    with open(TRADES_FILE, "w") as f:
        json.dump(trades, f, indent=2)

# ── Place order ───────────────────────────────────────────
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

# ── Volume check ──────────────────────────────────────────
def get_volume_data(symbol):
    try:
        end_time   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        start_time = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
        data       = client.get_historical_candle_data(
            trading_symbol=symbol,
            exchange=client.EXCHANGE_NSE,
            segment=client.SEGMENT_CASH,
            start_time=start_time,
            end_time=end_time,
            interval_in_minutes=60
        )
        candles        = data["candles"]
        volumes        = [c[5] for c in candles]
        avg_volume     = sum(volumes[-20:]) / max(len(volumes[-20:]), 1)
        current_volume = volumes[-1]
        volume_ratio   = round(current_volume / avg_volume, 2)
        high_volume    = current_volume >= avg_volume * 1.5
        return high_volume, volume_ratio
    except Exception as e:
        log.error(f"{symbol} volume error: {e}")
        return False, 0

# ── S/R + Volume signal ───────────────────────────────────
def get_sr_signal(symbol, current_price, level):
    support    = level["support"]
    resistance = level["resistance"]
    buffer     = level.get("buffer_pct", 0.5) / 100

    support_low   = support    * (1 - buffer)
    support_high  = support    * (1 + buffer)
    resist_low    = resistance * (1 - buffer)
    resist_high   = resistance * (1 + buffer)

    near_support    = support_low  <= current_price <= support_high
    near_resistance = resist_low   <= current_price <= resist_high

    if near_support:
        raw_signal = "BUY"
    elif near_resistance:
        raw_signal = "SELL"
    else:
        return "HOLD", support, resistance

    high_volume, volume_ratio = get_volume_data(symbol)
    if not high_volume:
        log.info(f"{symbol}: {raw_signal} near S/R but LOW volume ({volume_ratio}x) — skipping")
        return "HOLD", support, resistance

    log.info(f"{symbol}: {raw_signal} confirmed at S/R with {volume_ratio}x volume ✅")
    return raw_signal, support, resistance

# ── Process one stock ─────────────────────────────────────
def process_stock(symbol, level, trading_enabled=True):
    try:
        ltp_data      = client.get_ltp(
            segment=client.SEGMENT_CASH,
            exchange_trading_symbols=f"NSE_{symbol}"
        )
        current_price = ltp_data[f"NSE_{symbol}"]
        quantity      = level.get("quantity", 1)
        stop_loss     = round(current_price * STOP_PCT, 1)

        log.info(f"{symbol} ₹{current_price} | Signal: HOLD")

        if not trading_enabled:
            return

        signal, support, resistance = get_sr_signal(symbol, current_price, level)
        log.info(f"{symbol} ₹{current_price} | Support: ₹{support} | Resistance: ₹{resistance} | Signal: {signal}")

        if current_price <= stop_loss:
            signal = "STOP_LOSS"

        # ── NEWS GATE (runs only when a real trade is about to happen) ────────
        if signal in ("BUY", "SELL"):
            news = check_news_trigger(symbol, quantity)

            if not news["allowed"]:
                msg = (
                    f"🚫 NEWS BLOCK: {signal} {symbol} cancelled\n"
                    f"Sentiment: {news['sentiment']}\n"
                    f"Reason: {news['reason']}"
                )
                log.info(f"{symbol} | Signal: NEWS_BLOCK | {news['reason']}")
                send_telegram(msg)
                return                          # ← skip this trade entirely

            if news["qty"] != quantity:
                log.info(
                    f"{symbol} | BOOST: qty {quantity} → {news['qty']} "
                    f"({news['sentiment']} news: {news['reason']})"
                )
                quantity = news["qty"]          # ← use boosted quantity

            log.info(f"{symbol} | News: {news['decision']} | {news['sentiment']} | {news['reason']}")
        # ── END NEWS GATE ─────────────────────────────────────────────────────

        if signal == "BUY":
            order = place_order(symbol, client.TRANSACTION_TYPE_BUY, round(current_price, 1), quantity)
            msg   = f"✅ BUY {symbol}\nPrice: ₹{current_price}\nSupport: ₹{support}\nVolume confirmed!\nNews: {news['sentiment']} ✓"
            log.info(msg)
            send_telegram(msg)

        elif signal == "SELL":
            order = place_order(symbol, client.TRANSACTION_TYPE_SELL, round(current_price, 1), quantity)
            msg   = f"💰 SELL {symbol}\nPrice: ₹{current_price}\nResistance: ₹{resistance}\nVolume confirmed!\nNews: {news['sentiment']} ✓"
            log.info(msg)
            send_telegram(msg)

        elif signal == "STOP_LOSS":
            # Stop loss bypasses news check — always execute
            order = place_order(symbol, client.TRANSACTION_TYPE_SELL, round(current_price, 1), quantity)
            msg   = f"🛑 STOP LOSS {symbol}\nPrice: ₹{current_price}"
            log.info(msg)
            send_telegram(msg)

    except Exception as e:
        log.error(f"❌ Error processing {symbol}: {e}")

# ── Main loop ─────────────────────────────────────────────
while True:
    try:
        levels = load_levels()

        if not levels:
            log.info("No stocks in levels.json. Add stocks from dashboard.")
            time.sleep(300)
            continue

        market_open = is_market_open()

        if market_open:
            log.info(f"── Market OPEN | Scanning {len(levels)} stocks ────")
        else:
            log.info(f"── Market CLOSED | Fetching prices only ────────")

        for symbol, level in levels.items():
            process_stock(symbol, level, trading_enabled=market_open)
            time.sleep(1)

        log.info("── Scan complete. Next in 5 minutes ────")

    except Exception as e:
        log.error(f"❌ Bot error: {e}")
        send_telegram(f"❌ Bot Error: {e}")

    time.sleep(300)
