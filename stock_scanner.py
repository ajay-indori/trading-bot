import os
import json
import time
import logging
import urllib.request
import urllib.parse
from datetime import datetime, timedelta

log = logging.getLogger()

SUGGESTIONS_FILE = "suggestions.json"

# ── Your stock universe — edit this list freely ───────────
STOCK_UNIVERSE = [
    # Nifty 50
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK",
    "LT", "AXISBANK", "ASIANPAINT", "MARUTI", "SUNPHARMA",
    "TITAN", "BAJFINANCE", "WIPRO", "ULTRACEMCO", "NESTLEIND",
    "POWERGRID", "NTPC", "TECHM", "HCLTECH", "ONGC",
    "TATAMOTORS", "TATASTEEL", "JSWSTEEL", "BAJAJFINSV", "ADANIENT",
    # Mid caps
    "MOSCHIP", "PACEDIGITK", "URBANCO", "MPHASIS", "PERSISTENT",
    "COFORGE", "LTTS", "TATAELXSI", "DIXON", "AMBER",
    "VOLTAS", "HAVELLS", "POLYCAB", "KEI", "APARINDS",
    "DEEPAKNTR", "AAVAS", "CREDITACC", "FINEORG", "ALKYLAMINE",
    # Small caps
    "ZENTEC", "RATEGAIN", "NETWEB", "KAYNES", "IDEAFORGE",
]

# ── Scanner settings ──────────────────────────────────────
NEAR_LEVEL_PCT   = 1.5    # % within support/resistance to flag
MIN_VOLUME_RATIO = 1.3    # current volume must be 1.3x average
MAX_SUGGESTIONS  = 10     # max suggestions to show at once
SCAN_INTERVAL    = 1800   # scan every 30 minutes


def fetch_stock_data(symbol):
    """
    Fetch price + volume data for a symbol using Yahoo Finance (free, no API key).
    Returns (current_price, support, resistance, volume_ratio) or None on failure.
    """
    try:
        # Yahoo Finance ticker for NSE stocks
        ticker  = f"{symbol}.NS"
        url     = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=30d"
        headers = {"User-Agent": "Mozilla/5.0"}
        req     = urllib.request.Request(url, headers=headers)
        resp    = urllib.request.urlopen(req, timeout=10)
        data    = json.loads(resp.read().decode("utf-8"))

        chart   = data["chart"]["result"][0]
        closes  = chart["indicators"]["quote"][0]["close"]
        volumes = chart["indicators"]["quote"][0]["volume"]

        # Filter out None values
        closes  = [c for c in closes  if c is not None]
        volumes = [v for v in volumes if v is not None]

        if len(closes) < 10:
            return None

        current_price  = closes[-1]
        recent_closes  = closes[-20:]

        # Support = 20-day low, Resistance = 20-day high
        support        = round(min(recent_closes), 2)
        resistance     = round(max(recent_closes), 2)

        # Volume ratio
        avg_volume     = sum(volumes[-20:]) / max(len(volumes[-20:]), 1)
        current_volume = volumes[-1]
        volume_ratio   = round(current_volume / avg_volume, 2) if avg_volume > 0 else 0

        return current_price, support, resistance, volume_ratio

    except Exception as e:
        log.debug(f"[Scanner] {symbol} fetch failed: {e}")
        return None


def is_near_level(price, level, pct=NEAR_LEVEL_PCT):
    """Check if price is within pct% of a level."""
    return abs(price - level) / level * 100 <= pct


def scan_stocks():
    """
    Scan all stocks in STOCK_UNIVERSE.
    Returns list of suggestion dicts sorted by proximity to level.
    """
    log.info(f"[Scanner] Scanning {len(STOCK_UNIVERSE)} stocks...")
    suggestions = []

    # Load existing watchlist to skip already-tracked stocks
    watched = set()
    if os.path.exists("levels.json"):
        with open("levels.json") as f:
            watched = set(json.load(f).keys())

    for symbol in STOCK_UNIVERSE:
        if symbol in watched:
            continue  # already in watchlist

        result = fetch_stock_data(symbol)
        if not result:
            continue

        price, support, resistance, volume_ratio = result

        near_support    = is_near_level(price, support)
        near_resistance = is_near_level(price, resistance)
        high_volume     = volume_ratio >= MIN_VOLUME_RATIO

        if not (near_support or near_resistance):
            continue

        signal = "BUY"  if near_support    else "SELL"
        level  = support if near_support   else resistance
        proximity = round(abs(price - level) / level * 100, 2)

        suggestion = {
            "symbol":       symbol,
            "price":        round(price, 2),
            "support":      support,
            "resistance":   resistance,
            "signal":       signal,
            "proximity":    proximity,      # % away from level
            "volume_ratio": volume_ratio,
            "high_volume":  high_volume,
            "time":         datetime.now().strftime("%H:%M"),
            "reason":       f"Near {'support' if near_support else 'resistance'} "
                           f"({proximity}% away), volume {volume_ratio}x avg"
        }
        suggestions.append(suggestion)
        time.sleep(0.3)  # be gentle with Yahoo Finance

    # Sort: high volume first, then by proximity to level
    suggestions.sort(key=lambda x: (not x["high_volume"], x["proximity"]))
    suggestions = suggestions[:MAX_SUGGESTIONS]

    log.info(f"[Scanner] Found {len(suggestions)} suggestions")
    return suggestions


def save_suggestions(suggestions):
    with open(SUGGESTIONS_FILE, "w") as f:
        json.dump(suggestions, f, indent=2)


def load_suggestions():
    if os.path.exists(SUGGESTIONS_FILE):
        with open(SUGGESTIONS_FILE) as f:
            return json.load(f)
    return []


def run_scanner():
    while True:
        try:
            from datetime import timezone, timedelta
            IST = timezone(timedelta(hours=5, minutes=30))
            now = datetime.now(IST)
            if now.weekday() < 5:
                market_open  = now.replace(hour=9,  minute=0,  second=0)
                market_close = now.replace(hour=16, minute=0,  second=0)
                if market_open <= now <= market_close:
                    suggestions = scan_stocks()
                    save_suggestions(suggestions)
                else:
                    log.info("[Scanner] Outside market hours, skipping scan")
            else:
                log.info("[Scanner] Weekend, skipping scan")
        except Exception as e:
            log.error(f"[Scanner] Error: {e}")

        time.sleep(SCAN_INTERVAL)
