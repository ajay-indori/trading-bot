import threading
import subprocess
import sys

def run_bot():
    subprocess.run([sys.executable, "bot.py"])

def run_dashboard():
    subprocess.run([sys.executable, "dashboard.py"])

# Run bot in background thread
bot_thread = threading.Thread(target=run_bot)
bot_thread.daemon = True
bot_thread.start()

# Run dashboard in main thread
run_dashboard()