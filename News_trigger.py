import os
import json
import urllib.request
import urllib.parse
import re
import logging

log = logging.getLogger()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
BOOST_MULTIPLIER  = 1.5   # qty multiplier on strong positive news
MAX_ARTICLES      = 5     # how many headlines to analyse


def fetch_news_headlines(symbol):
    """Fetch top headlines from Google News RSS for a stock symbol."""
    query   = urllib.parse.quote(f"{symbol} stock NSE India")
    url     = f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        req      = urllib.request.Request(url, headers=headers)
        response = urllib.request.urlopen(req, timeout=10)
        xml      = response.read().decode("utf-8", errors="ignore")

        titles  = []
        pattern = re.compile(r"<item>.*?<title>(.*?)</title>", re.DOTALL)
        for match in pattern.finditer(xml):
            if len(titles) >= MAX_ARTICLES:
                break
            title = match.group(1)
            title = re.sub(r"<!\[CDATA\[|\]\]>", "", title)
            title = title.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").strip()
            if title:
                titles.append(title)

        log.info(f"[NewsTrigger] {symbol}: {len(titles)} headlines fetched")
        return titles

    except Exception as e:
        log.error(f"[NewsTrigger] RSS fetch failed for {symbol}: {e}")
        return []


def analyse_sentiment(symbol, headlines):
    """Send headlines to Claude API and get a trade decision."""
    if not ANTHROPIC_API_KEY:
        log.warning("[NewsTrigger] ANTHROPIC_API_KEY not set — skipping, allowing trade")
        return {"decision": "ALLOW", "sentiment": "NEUTRAL", "reason": "No API key", "confidence": 0}

    if not headlines:
        return {"decision": "ALLOW", "sentiment": "NEUTRAL", "reason": "No news found", "confidence": 0}

    numbered = "\n".join(f"{i+1}. {h}" for i, h in enumerate(headlines))
    prompt   = f"""You are a stock trading risk filter for Indian equities.

Analyse the sentiment of these recent news headlines for the stock "{symbol}":
{numbered}

Respond ONLY with a JSON object (no markdown, no explanation):
{{
  "sentiment": "POSITIVE" or "NEGATIVE" or "NEUTRAL",
  "confidence": 0.0 to 1.0,
  "reason": "one short sentence",
  "decision": "ALLOW" or "BOOST" or "BLOCK"
}}

Rules:
- BLOCK  → sentiment NEGATIVE with confidence > 0.6 (bad earnings, fraud, crash, regulatory issues)
- BOOST  → sentiment POSITIVE with confidence > 0.7 (good results, contract wins, upgrades)
- ALLOW  → everything else (neutral / mixed / low confidence)"""

    body = json.dumps({
        "model":      "claude-sonnet-4-20250514",
        "max_tokens": 200,
        "messages":   [{"role": "user", "content": prompt}]
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data    = body,
        headers = {
            "Content-Type":      "application/json",
            "x-api-key":         ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01"
        },
        method = "POST"
    )

    try:
        response = urllib.request.urlopen(req, timeout=15)
        data     = json.loads(response.read().decode("utf-8"))
        text     = data["content"][0]["text"].strip()
        text     = re.sub(r"```json|```", "", text).strip()
        result   = json.loads(text)
        log.info(f"[NewsTrigger] {symbol} → {result['decision']} | {result['sentiment']} | {result['reason']}")
        return result

    except Exception as e:
        log.error(f"[NewsTrigger] Claude API error: {e}")
        return {"decision": "ALLOW", "sentiment": "NEUTRAL", "reason": "API error", "confidence": 0}


def check_news_trigger(symbol, qty=1):
    """
    Main function — call this BEFORE placing any trade.

    Returns a dict:
      allowed   : bool   — False means skip the trade entirely
      qty       : int    — adjusted quantity (boosted if positive news)
      decision  : str    — ALLOW / BOOST / BLOCK
      sentiment : str    — POSITIVE / NEGATIVE / NEUTRAL
      reason    : str    — one-line explanation
      headlines : list   — raw headlines fetched
    """
    log.info(f"[NewsTrigger] Checking news for {symbol}...")

    headlines = fetch_news_headlines(symbol)
    analysis  = analyse_sentiment(symbol, headlines)

    allowed      = analysis["decision"] != "BLOCK"
    multiplier   = BOOST_MULTIPLIER if analysis["decision"] == "BOOST" else 1.0
    adjusted_qty = round(qty * multiplier) if allowed else 0

    return {
        "allowed":   allowed,
        "qty":       adjusted_qty,
        "decision":  analysis["decision"],
        "sentiment": analysis["sentiment"],
        "reason":    analysis.get("reason", ""),
        "confidence":analysis.get("confidence", 0),
        "headlines": headlines
    }
