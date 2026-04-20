import threading
import subprocess
import sys
import logging
from stock_scanner import run_scanner

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")

def run_bot():
    subprocess.run([sys.executable, "bot.py"])

def run_dashboard():
    subprocess.run([sys.executable, "dashboard.py"])

# Run scanner in background thread
scanner_thread = threading.Thread(target=run_scanner)
scanner_thread.daemon = True
scanner_thread.start()

# Run bot in background thread
bot_thread = threading.Thread(target=run_bot)
bot_thread.daemon = True
bot_thread.start()

# Run dashboard in main thread
run_dashboard()
