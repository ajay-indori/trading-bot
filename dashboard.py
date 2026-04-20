from flask import Flask, jsonify, render_template_string, request, session, redirect, url_for
from functools import wraps
import os, re, json
os.chdir(os.path.dirname(os.path.abspath(__file__)))
from stock_scanner import load_suggestions
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get("DASHBOARD_SECRET_KEY", "changeme-set-in-railway")

DASHBOARD_USER = os.environ.get("DASHBOARD_USER", "admin")
DASHBOARD_PASS = os.environ.get("DASHBOARD_PASS", "admin")

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

LOGIN_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Trading Bot — Login</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Syne:wght@800&display=swap" rel="stylesheet">
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  body{background:#080c10;color:#c9d1d9;font-family:"Space Mono",monospace;min-height:100vh;display:flex;align-items:center;justify-content:center}
  body::before{content:"";position:fixed;inset:0;background-image:linear-gradient(rgba(0,255,136,0.03) 1px,transparent 1px),linear-gradient(90deg,rgba(0,255,136,0.03) 1px,transparent 1px);background-size:40px 40px;pointer-events:none}
  .login-box{background:#0d1117;border:1px solid #1e2d3d;border-radius:12px;padding:48px 40px;width:100%;max-width:380px;position:relative;z-index:1}
  .login-box::before{content:"";position:absolute;top:0;left:0;right:0;height:2px;background:#00ff88;border-radius:12px 12px 0 0}
  .logo{font-family:"Syne",sans-serif;font-size:20px;font-weight:800;margin-bottom:8px;text-align:center}
  .logo span{color:#00ff88}
  .subtitle{font-size:10px;letter-spacing:2px;text-transform:uppercase;color:#4a5568;text-align:center;margin-bottom:36px}
  .form-group{display:flex;flex-direction:column;gap:6px;margin-bottom:16px}
  .form-label{font-size:10px;letter-spacing:1px;text-transform:uppercase;color:#4a5568}
  .form-input{background:#0a0f16;border:1px solid #1e2d3d;border-radius:4px;color:#c9d1d9;font-family:"Space Mono",monospace;font-size:13px;padding:10px 14px;outline:none;transition:border-color 0.2s;width:100%}
  .form-input:focus{border-color:#00ff88}
  .login-btn{background:#00ff88;border:none;border-radius:4px;color:#000;cursor:pointer;font-family:"Space Mono",monospace;font-size:12px;font-weight:700;letter-spacing:1px;padding:12px;transition:all 0.2s;width:100%;margin-top:8px}
  .login-btn:hover{background:#00cc6a}
  .error{background:rgba(255,68,68,0.1);border:1px solid rgba(255,68,68,0.3);border-radius:4px;color:#ff4444;font-size:11px;padding:10px 14px;margin-bottom:16px;text-align:center}
</style>
</head>
<body>
<div class="login-box">
  <div class="logo">TRADE <span>BOT</span></div>
  <div class="subtitle">Secure Access Required</div>
  {% if error %}<div class="error">{{ error }}</div>{% endif %}
  <form method="POST" action="/login">
    <div class="form-group">
      <label class="form-label">Username</label>
      <input class="form-input" type="text" name="username" placeholder="Enter username" autofocus>
    </div>
    <div class="form-group">
      <label class="form-label">Password</label>
      <input class="form-input" type="password" name="password" placeholder="Enter password">
    </div>
    <button class="login-btn" type="submit">ACCESS DASHBOARD</button>
  </form>
</div>
</body>
</html>'''

LOG_FILE    = "bot_log.txt"
TRADES_FILE = "trades.json"
LEVELS_FILE = "levels.json"

# ── Data helpers ──────────────────────────────────────────
def load_levels():
    if os.path.exists(LEVELS_FILE):
        with open(LEVELS_FILE) as f:
            return json.load(f)
    return {}

def save_levels(levels):
    with open(LEVELS_FILE, "w") as f:
        json.dump(levels, f, indent=2)

def parse_logs():
    trades, signals, errors = [], [], []
    if not os.path.exists(LOG_FILE):
        return trades, signals, errors
    with open(LOG_FILE, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(" | ", 1)
            timestamp, message = (parts[0], parts[1]) if len(parts) == 2 else ("", line)
            if "Signal:" in message:
                signals.append({"time": timestamp, "message": message})
            elif any(x in message for x in ["BUY Order", "SELL Order", "STOP LOSS", "Order Placed"]):
                trades.append({"time": timestamp, "message": message})
            elif "Error" in message or "error" in message:
                errors.append({"time": timestamp, "message": message})
    return trades[-20:][::-1], signals[-100:][::-1], errors[-10:][::-1]

def get_latest_prices(signals):
    levels  = load_levels()
    prices, latest_signals = {}, {}
    for s in signals:
        for stock in levels.keys():
            if stock in s["message"] and stock not in prices:
                price_match = re.search(r'[\u20b9]([\d.]+)', s["message"])
                sig_match   = re.search(r'Signal: (\w+)', s["message"])
                if price_match:
                    prices[stock]         = price_match.group(1)
                    latest_signals[stock] = sig_match.group(1) if sig_match else "HOLD"
    return prices, latest_signals

def get_pnl_data():
    if not os.path.exists(TRADES_FILE):
        return [], 0, 0
    with open(TRADES_FILE) as f:
        trades = json.load(f)
    pnl_trades = [t for t in trades if t.get("pnl") not in (None, "closed")]
    total_pnl  = round(sum(t["pnl"] for t in pnl_trades), 2)
    win_trades = len([t for t in pnl_trades if t["pnl"] > 0])
    return trades[-30:][::-1], total_pnl, win_trades

def get_bot_status():
    if not os.path.exists(LOG_FILE):
        return "UNKNOWN"
    diff = (datetime.now() - datetime.fromtimestamp(os.path.getmtime(LOG_FILE))).seconds
    return "RUNNING" if diff < 400 else "STOPPED"

# ── API Routes ────────────────────────────────────────────
@app.route('/api/data')
@login_required
def api_data():
    trades, signals, errors = parse_logs()
    prices, latest_signals  = get_latest_prices(signals)
    pnl_trades, total_pnl, win_trades = get_pnl_data()
    levels = load_levels()
    return jsonify({
        "status":         get_bot_status(),
        "trades":         trades,
        "signals":        signals,
        "errors":         errors,
        "prices":         prices,
        "latest_signals": latest_signals,
        "pnl_trades":     pnl_trades,
        "total_pnl":      total_pnl,
        "win_trades":     win_trades,
        "levels":         levels
    })

@app.route('/api/levels', methods=['GET'])
@login_required
def get_levels():
    return jsonify(load_levels())

@app.route('/api/levels/add', methods=['POST'])
@login_required
def add_level():
    data   = request.json
    symbol = data.get("symbol", "").upper().strip()
    if not symbol:
        return jsonify({"success": False, "error": "Symbol is required"})
    levels = load_levels()
    levels[symbol] = {
        "support":    float(data.get("support", 0)),
        "resistance": float(data.get("resistance", 0)),
        "buffer_pct": float(data.get("buffer_pct", 0.5)),
        "quantity":   int(data.get("quantity", 1))
    }
    save_levels(levels)
    return jsonify({"success": True, "message": f"{symbol} added successfully"})

@app.route('/api/levels/delete', methods=['POST'])
@login_required
def delete_level():
    symbol = request.json.get("symbol", "").upper().strip()
    levels = load_levels()
    if symbol in levels:
        del levels[symbol]
        save_levels(levels)
        return jsonify({"success": True, "message": f"{symbol} removed"})
    return jsonify({"success": False, "error": f"{symbol} not found"})

@app.route('/api/suggestions')
@app.route('/api/suggestions/scan', methods=['POST'])
def trigger_scan():
    try:
        from stock_scanner import scan_stocks, save_suggestions
        suggestions = scan_stocks()
        save_suggestions(suggestions)
        return jsonify({"success": True, "count": len(suggestions)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
        
@login_required
def get_suggestions():
    return jsonify(load_suggestions())

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if (request.form.get('username') == DASHBOARD_USER and
                request.form.get('password') == DASHBOARD_PASS):
            session['logged_in'] = True
            return redirect(url_for('index'))
        error = 'Invalid username or password'
    return render_template_string(LOGIN_HTML, error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ── HTML Dashboard ────────────────────────────────────────
HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Trading Bot Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Syne:wght@400;700;800&display=swap" rel="stylesheet">
<style>
  :root {
    --bg:#080c10; --surface:#0d1117; --border:#1e2d3d;
    --accent:#00ff88; --accent3:#4da6ff;
    --text:#c9d1d9; --muted:#4a5568;
    --buy:#00ff88; --sell:#ff4444; --hold:#4da6ff; --stop:#ff6b35;
  }
  *{margin:0;padding:0;box-sizing:border-box}
  body{background:var(--bg);color:var(--text);font-family:'Space Mono',monospace;min-height:100vh}
  body::before{content:'';position:fixed;inset:0;background-image:linear-gradient(rgba(0,255,136,0.03) 1px,transparent 1px),linear-gradient(90deg,rgba(0,255,136,0.03) 1px,transparent 1px);background-size:40px 40px;pointer-events:none;z-index:0}
  .container{max-width:1300px;margin:0 auto;padding:24px;position:relative;z-index:1}

  header{display:flex;align-items:center;justify-content:space-between;padding:24px 0 32px;border-bottom:1px solid var(--border);margin-bottom:32px}
  .logo{font-family:'Syne',sans-serif;font-size:22px;font-weight:800}
  .logo span{color:var(--accent)}
  .live-badge{display:flex;align-items:center;gap:8px;font-size:11px;letter-spacing:2px;text-transform:uppercase;color:var(--muted)}
  .pulse{width:8px;height:8px;border-radius:50%;background:var(--accent);animation:pulse 2s infinite}
  .pulse.stopped{background:var(--sell);animation:none}
  @keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:0.4;transform:scale(0.8)}}

  /* Stock cards */
  .stocks-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px;margin-bottom:28px}
  .stock-card{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:16px;position:relative;overflow:hidden}
  .stock-card::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:var(--muted);transition:background 0.3s}
  .stock-card.BUY::before{background:var(--buy)}
  .stock-card.SELL::before{background:var(--sell)}
  .stock-card.HOLD::before{background:var(--hold)}
  .stock-card.STOP_LOSS::before{background:var(--stop)}
  .stock-symbol{font-family:'Syne',sans-serif;font-size:15px;font-weight:800;margin-bottom:4px}
  .stock-price{font-size:18px;font-weight:700;color:var(--accent);margin-bottom:4px}
  .stock-price.no-data{font-size:13px;color:var(--muted)}
  .stock-levels{font-size:10px;color:var(--muted);margin-bottom:8px}
  .signal-badge{display:inline-block;padding:2px 10px;border-radius:4px;font-size:10px;font-weight:700;letter-spacing:1px}
  .badge-BUY{background:rgba(0,255,136,0.15);color:var(--buy);border:1px solid rgba(0,255,136,0.3)}
  .badge-SELL{background:rgba(255,68,68,0.15);color:var(--sell);border:1px solid rgba(255,68,68,0.3)}
  .badge-HOLD{background:rgba(77,166,255,0.15);color:var(--hold);border:1px solid rgba(77,166,255,0.3)}
  .badge-STOP_LOSS{background:rgba(255,107,53,0.15);color:var(--stop);border:1px solid rgba(255,107,53,0.3)}
  .badge-WAITING{background:rgba(74,85,104,0.15);color:var(--muted);border:1px solid rgba(74,85,104,0.3)}
  .card-actions{position:absolute;top:6px;right:6px;display:flex;flex-direction:column;gap:2px}
  .edit-btn{background:rgba(255,200,0,0.15);border:none;color:#ffc800;cursor:pointer;font-size:13px;padding:2px 6px;border-radius:4px;transition:all 0.2s}
  .edit-btn:hover{background:rgba(255,200,0,0.3);color:#ffd700}
  .delete-btn{background:rgba(255,68,68,0.15);border:none;color:#ff4444;cursor:pointer;font-size:14px;padding:2px 6px;border-radius:4px;transition:all 0.2s}
  .delete-btn:hover{background:rgba(255,68,68,0.35);color:#ff0000}

  /* Stats */
  .stats-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:16px;margin-bottom:28px}
  .stat-card{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:18px 20px;position:relative;overflow:hidden}
  .stat-card::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:var(--muted)}
  .stat-card.green::before{background:var(--buy)}
  .stat-card.red::before{background:var(--sell)}
  .stat-card.blue::before{background:var(--accent3)}
  .stat-card.orange::before{background:var(--stop)}
  .stat-label{font-size:10px;letter-spacing:2px;text-transform:uppercase;color:var(--muted);margin-bottom:8px}
  .stat-value{font-family:'Syne',sans-serif;font-size:22px;font-weight:800;color:var(--accent)}
  .stat-card.red .stat-value{color:var(--sell)}
  .stat-card.blue .stat-value{color:var(--accent3)}
  .stat-card.orange .stat-value{color:var(--stop)}

  /* Status bar */
  .status-bar{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:14px 24px;margin-bottom:24px;display:flex;align-items:center;gap:24px;font-size:12px}
  .status-item{display:flex;align-items:center;gap:8px}
  .status-dot{width:6px;height:6px;border-radius:50%}
  .status-dot.green{background:var(--accent);box-shadow:0 0 8px var(--accent)}
  .status-dot.red{background:var(--sell)}
  .status-dot.grey{background:var(--muted)}
  .status-label{color:var(--muted);font-size:10px;letter-spacing:1px;text-transform:uppercase}
  .status-value{font-weight:700}

  /* Add stock form */
  .add-stock-panel{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:20px 24px;margin-bottom:24px}
  .add-stock-title{font-size:10px;letter-spacing:2px;text-transform:uppercase;color:var(--muted);margin-bottom:16px}
  .form-grid{display:grid;grid-template-columns:2fr 1fr 1fr 1fr 1fr auto;gap:12px;align-items:end}
  .form-group{display:flex;flex-direction:column;gap:6px}
  .form-label{font-size:10px;letter-spacing:1px;text-transform:uppercase;color:var(--muted)}
  .form-input{background:#0a0f16;border:1px solid var(--border);border-radius:4px;color:var(--text);font-family:'Space Mono',monospace;font-size:13px;padding:8px 12px;outline:none;transition:border-color 0.2s;width:100%}
  .form-input:focus{border-color:var(--accent)}
  .form-input::placeholder{color:var(--muted)}
  .add-btn{background:var(--accent);border:none;border-radius:4px;color:#000;cursor:pointer;font-family:'Space Mono',monospace;font-size:12px;font-weight:700;letter-spacing:1px;padding:9px 20px;transition:all 0.2s;white-space:nowrap}
  .add-btn:hover{background:#00cc6a}
  .add-btn:disabled{background:var(--muted);cursor:not-allowed}

  /* Toast */
  .toast{position:fixed;bottom:24px;right:24px;background:var(--surface);border:1px solid var(--accent);border-radius:8px;padding:12px 20px;font-size:12px;color:var(--accent);z-index:1000;opacity:0;transform:translateY(10px);transition:all 0.3s;pointer-events:none}
  .toast.error{border-color:var(--sell);color:var(--sell)}
  .toast.show{opacity:1;transform:translateY(0)}

  /* Panels */
  .main-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:20px}
  .panel{background:var(--surface);border:1px solid var(--border);border-radius:8px;overflow:hidden}
  .panel-header{padding:14px 20px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between}
  .panel-title{font-size:10px;letter-spacing:2px;text-transform:uppercase;color:var(--muted)}
  .panel-count{font-size:11px;color:var(--accent);background:rgba(0,255,136,0.1);padding:2px 8px;border-radius:20px}
  .panel-body{padding:12px 20px;max-height:280px;overflow-y:auto}
  .panel-body::-webkit-scrollbar{width:4px}
  .panel-body::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}
  .log-row{display:flex;gap:12px;padding:9px 0;border-bottom:1px solid rgba(30,45,61,0.5);font-size:12px}
  .log-row:last-child{border-bottom:none}
  .log-time{color:var(--muted);white-space:nowrap;flex-shrink:0;font-size:10px}
  .full-panel{grid-column:1/-1}
  .empty-state{text-align:center;padding:36px 20px;color:var(--muted);font-size:11px;letter-spacing:1px}

  /* Suggestions */
  .suggestion-card{display:flex;align-items:center;justify-content:space-between;padding:10px 0;border-bottom:1px solid rgba(30,45,61,0.5);gap:12px}
  .suggestion-card:last-child{border-bottom:none}
  .sug-info{flex:1;min-width:0}
  .sug-symbol{font-family:'Syne',sans-serif;font-size:14px;font-weight:800}
  .sug-price{font-size:13px;color:var(--accent);font-weight:700}
  .sug-reason{font-size:10px;color:var(--muted);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .sug-vol{font-size:10px;padding:2px 6px;border-radius:4px;background:rgba(0,255,136,0.1);color:var(--accent);border:1px solid rgba(0,255,136,0.2);white-space:nowrap}
  .sug-vol.low{background:rgba(74,85,104,0.1);color:var(--muted);border-color:rgba(74,85,104,0.2)}
  .add-sug-btn{background:var(--accent);border:none;border-radius:4px;color:#000;cursor:pointer;font-family:'Space Mono',monospace;font-size:10px;font-weight:700;padding:5px 12px;transition:all 0.2s;white-space:nowrap}
  .add-sug-btn:hover{background:#00cc6a}
  .add-sug-btn.added{background:var(--muted);cursor:default}

  /* P&L Table */
  .pnl-table{width:100%;border-collapse:collapse;font-size:12px}
  .pnl-table th{text-align:left;padding:8px 12px;font-size:10px;letter-spacing:2px;text-transform:uppercase;color:var(--muted);border-bottom:1px solid var(--border)}
  .pnl-table td{padding:10px 12px;border-bottom:1px solid rgba(30,45,61,0.5)}
  .pnl-table tr:last-child td{border-bottom:none}
  .pnl-positive{color:var(--buy);font-weight:700}
  .pnl-negative{color:var(--sell);font-weight:700}
  .pnl-pending{color:var(--muted)}

  .refresh-btn{background:transparent;border:1px solid var(--border);color:var(--muted);padding:6px 16px;border-radius:4px;font-family:'Space Mono',monospace;font-size:11px;letter-spacing:1px;cursor:pointer;transition:all 0.2s}
  .refresh-btn:hover{border-color:var(--accent);color:var(--accent)}

  @media(max-width:900px){.stats-grid{grid-template-columns:repeat(2,1fr)}.main-grid{grid-template-columns:1fr}.form-grid{grid-template-columns:1fr 1fr}}
</style>
</head>
<body>
<div class="container">
  <header>
    <div class="logo">MULTI-STOCK <span>TRADE BOT</span></div>
    <div style="display:flex;align-items:center;gap:16px">
      <button class="refresh-btn" onclick="loadData()">&#8635; REFRESH</button>
      <div class="live-badge"><div class="pulse" id="statusPulse"></div><span id="statusText">CHECKING...</span></div>
    </div>
  </header>

  <!-- Add Stock Form -->
  <div class="add-stock-panel">
    <div class="add-stock-title">&#43; Add / Update Stock</div>
    <div class="form-grid">
      <div class="form-group">
        <label class="form-label">Stock Symbol</label>
        <input class="form-input" id="f-symbol" placeholder="e.g. WIPRO" oninput="this.value=this.value.toUpperCase()">
      </div>
      <div class="form-group">
        <label class="form-label">Support (&#8377;)</label>
        <input class="form-input" id="f-support" type="number" placeholder="1280">
      </div>
      <div class="form-group">
        <label class="form-label">Resistance (&#8377;)</label>
        <input class="form-input" id="f-resistance" type="number" placeholder="1400">
      </div>
      <div class="form-group">
        <label class="form-label">Buffer %</label>
        <input class="form-input" id="f-buffer" type="number" placeholder="0.5" value="0.5" step="0.1">
      </div>
      <div class="form-group">
        <label class="form-label">Quantity</label>
        <input class="form-input" id="f-quantity" type="number" placeholder="1" value="1">
      </div>
      <button class="add-btn" onclick="addStock()" id="addBtn">ADD STOCK</button>
    </div>
  </div>

  <!-- Stock Cards -->
  <div class="stocks-grid" id="stocksGrid">
    <div class="empty-state" style="grid-column:1/-1">Loading stocks...</div>
  </div>

  <!-- Stats -->
  <div class="stats-grid">
    <div class="stat-card green"><div class="stat-label">Total P&amp;L</div><div class="stat-value" id="totalPnl">&#8377;0</div></div>
    <div class="stat-card blue"><div class="stat-label">Winning Trades</div><div class="stat-value" id="winTrades">0</div></div>
    <div class="stat-card"><div class="stat-label">Stocks Watched</div><div class="stat-value" id="stockCount">0</div></div>
    <div class="stat-card red"><div class="stat-label">Total Trades</div><div class="stat-value" id="totalTrades">0</div></div>
    <div class="stat-card orange"><div class="stat-label">Errors</div><div class="stat-value" id="totalErrors">0</div></div>
  </div>

  <!-- Status bar -->
  <div class="status-bar">
    <div class="status-item"><div class="status-dot" id="botDot"></div><span class="status-label">Bot</span><span class="status-value" id="botStatus">&#8212;</span></div>
    <div class="status-item"><div class="status-dot" id="marketDot"></div><span class="status-label">Market</span><span class="status-value" id="marketStatus">&#8212;</span></div>
    <div class="status-item"><span class="status-label">Last Updated</span><span class="status-value" id="lastUpdated">&#8212;</span></div>
  </div>

  <!-- Panels -->
  <div class="main-grid">

    <!-- Signal History -->
    <div class="panel-header">
      <span class="panel-title">&#128269; Stock Suggestions</span>
      <div style="display:flex;align-items:center;gap:10px">
        <span style="font-size:10px;color:var(--muted)" id="lastScanTime"></span>
        <button class="add-btn" id="scanBtn" onclick="triggerScan()" style="padding:4px 14px;font-size:10px">&#128269; SCAN NOW</button>
        <span class="panel-count" id="sugCount">0</span>
      </div>
    </div>

    <!-- Error Log -->
    <div class="panel">
      <div class="panel-header"><span class="panel-title">Error Log</span><span class="panel-count" id="errorCount">0</span></div>
      <div class="panel-body" id="errorsList"><div class="empty-state">NO ERRORS &#8212; ALL CLEAR &#10003;</div></div>
    </div>

    <!-- Stock Suggestions -->
    <div class="panel full-panel">
      <div class="panel-header">
        <span class="panel-title">&#128269; Stock Suggestions</span>
        <span class="panel-count" id="sugCount">0</span>
      </div>
      <div class="panel-body" id="sugList">
        <div class="empty-state">Scanning stocks... check back in a few minutes during market hours</div>
      </div>
    </div>

    <!-- P&L Trade History -->
    <div class="panel full-panel">
      <div class="panel-header"><span class="panel-title">P&amp;L Trade History</span><span class="panel-count" id="pnlCount">0</span></div>
      <div class="panel-body">
        <table class="pnl-table">
          <thead><tr><th>Time</th><th>Stock</th><th>Action</th><th>Price</th><th>Qty</th><th>P&amp;L</th></tr></thead>
          <tbody id="pnlTableBody"><tr><td colspan="6" style="text-align:center;padding:36px;color:var(--muted);font-size:11px">NO TRADES YET</td></tr></tbody>
        </table>
      </div>
    </div>

  </div><!-- end main-grid -->
</div><!-- end container -->

<!-- Toast notification -->
<div class="toast" id="toast"></div>

<script>
function showToast(msg, isError=false){
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast' + (isError ? ' error' : '') + ' show';
  setTimeout(() => t.className = 'toast', 3000);
}

function isMarketOpen(){
  const n=new Date(), d=n.getDay();
  if(d===0||d===6) return false;
  const m=n.getHours()*60+n.getMinutes();
  return m>=9*60+15&&m<=15*60+30;
}

function badgeHTML(s){
  return `<span class="signal-badge badge-${s||'WAITING'}">${s||'WAITING'}</span>`;
}

async function addStock(){
  const symbol     = document.getElementById('f-symbol').value.trim().toUpperCase();
  const support    = document.getElementById('f-support').value;
  const resistance = document.getElementById('f-resistance').value;
  const buffer     = document.getElementById('f-buffer').value || 0.5;
  const quantity   = document.getElementById('f-quantity').value || 1;

  if(!symbol || !support || !resistance){
    showToast('Please fill Symbol, Support and Resistance', true);
    return;
  }
  if(parseFloat(support) >= parseFloat(resistance)){
    showToast('Support must be less than Resistance', true);
    return;
  }

  const btn = document.getElementById('addBtn');
  btn.disabled = true;
  btn.textContent = 'ADDING...';

  try {
    const res  = await fetch('/api/levels/add', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({symbol, support, resistance, buffer_pct: buffer, quantity})
    });
    const data = await res.json();
    if(data.success){
      showToast(`✅ ${symbol} added! Bot will pick it up next scan.`);
      document.getElementById('f-symbol').value     = '';
      document.getElementById('f-support').value    = '';
      document.getElementById('f-resistance').value = '';
      document.getElementById('f-quantity').value   = '1';
      document.getElementById('addBtn').textContent = 'ADD STOCK';
      loadData();
    } else {
      showToast(data.error, true);
    }
  } catch(e){
    showToast('Failed to add stock', true);
  }

  btn.disabled = false;
  btn.textContent = btn.textContent === 'ADDING...' ? 'ADD STOCK' : btn.textContent;
}

async function deleteStock(symbol){
  if(!confirm(`Remove ${symbol} from your watchlist?`)) return;
  const res  = await fetch('/api/levels/delete', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({symbol})
  });
  const data = await res.json();
  if(data.success){
    showToast(`${symbol} removed`);
    loadData();
  } else {
    showToast(data.error, true);
  }
}

function editStock(symbol, support, resistance, buffer, quantity){
  document.getElementById('f-symbol').value     = symbol;
  document.getElementById('f-support').value    = support;
  document.getElementById('f-resistance').value = resistance;
  document.getElementById('f-buffer').value     = buffer;
  document.getElementById('f-quantity').value   = quantity;
  document.getElementById('addBtn').textContent = 'UPDATE STOCK';
  document.querySelector('.add-stock-panel').scrollIntoView({behavior:'smooth'});
}

async function addFromSuggestion(symbol, support, resistance){
  const res = await fetch('/api/levels/add', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({symbol, support, resistance, buffer_pct: 0.5, quantity: 1})
  });
  const data = await res.json();
  if(data.success){
    showToast('✅ ' + symbol + ' added to watchlist!');
    loadData();
  } else {
    showToast(data.error, true);
  }
}
async function triggerScan(){
  const btn = document.getElementById('scanBtn');
  btn.disabled = true;
  btn.textContent = '⏳ SCANNING...';
  try {
    const res  = await fetch('/api/suggestions/scan', {method:'POST'});
    const data = await res.json();
    if(data.success){
      document.getElementById('lastScanTime').textContent = 'Last scan: ' + new Date().toLocaleTimeString();
      showToast('✅ Found ' + data.count + ' suggestions!');
      loadData();
    } else {
      showToast('Scan failed: ' + data.error, true);
    }
  } catch(e){
    showToast('Scan error', true);
  }
  btn.disabled = false;
  btn.textContent = '🔍 SCAN NOW';
}
async function loadData(){
  try{
    const data = await (await fetch('/api/data')).json();

    // Status
    const running = data.status==='RUNNING';
    document.getElementById('statusPulse').className = 'pulse'+(running?'':' stopped');
    document.getElementById('statusText').textContent = running?'BOT LIVE':'BOT STOPPED';
    document.getElementById('botDot').className = 'status-dot '+(running?'green':'red');
    document.getElementById('botStatus').textContent = data.status;
    const mkt = isMarketOpen();
    document.getElementById('marketDot').className = 'status-dot '+(mkt?'green':'grey');
    document.getElementById('marketStatus').textContent = mkt?'OPEN':'CLOSED';
    document.getElementById('lastUpdated').textContent = new Date().toLocaleTimeString();

    // Stats
    const levels = data.levels || {};
    document.getElementById('stockCount').textContent  = Object.keys(levels).length;
    document.getElementById('totalTrades').textContent = data.trades.length;
    document.getElementById('totalErrors').textContent = data.errors.length;
    document.getElementById('signalCount').textContent = data.signals.length;
    document.getElementById('errorCount').textContent  = data.errors.length;
    document.getElementById('winTrades').textContent   = data.win_trades || 0;
    document.getElementById('pnlCount').textContent    = data.pnl_trades ? data.pnl_trades.length : 0;

    const pnl   = data.total_pnl || 0;
    const pnlEl = document.getElementById('totalPnl');
    pnlEl.innerHTML = (pnl >= 0 ? '+' : '') + '&#8377;' + pnl;
    pnlEl.style.color = pnl >= 0 ? 'var(--buy)' : 'var(--sell)';

    // Stock cards
    const grid   = document.getElementById('stocksGrid');
    const prices = data.prices || {};
    const sigs   = data.latest_signals || {};

    if(Object.keys(levels).length === 0){
      grid.innerHTML = '<div class="empty-state" style="grid-column:1/-1">No stocks added yet. Use the form above to add your first stock!</div>';
    } else {
      grid.innerHTML = Object.entries(levels).map(([symbol, lvl]) => {
        const price = prices[symbol];
        const sig   = sigs[symbol];
        return `
        <div class="stock-card ${sig||''}">
          <div class="card-actions">
            <button class="edit-btn" onclick="editStock('${symbol}',${lvl.support},${lvl.resistance},${lvl.buffer_pct},${lvl.quantity})" title="Edit">&#9998;</button>
            <button class="delete-btn" onclick="deleteStock('${symbol}')" title="Remove">&#10005;</button>
          </div>
          <div class="stock-symbol">${symbol}</div>
          <div class="stock-price ${price?'':'no-data'}">${price ? '&#8377;'+price : '&#8212;'}</div>
          <div class="stock-levels">S: &#8377;${lvl.support} &nbsp;|&nbsp; R: &#8377;${lvl.resistance}</div>
          <div class="stock-levels">Qty: ${lvl.quantity} &nbsp;|&nbsp; Buffer: ${lvl.buffer_pct}%</div>
          ${badgeHTML(sig)}
        </div>`;
      }).join('');
    }

    // Signals
    const sEl = document.getElementById('signalsList');
    sEl.innerHTML = data.signals.length===0
      ? '<div class="empty-state">NO SIGNALS YET</div>'
      : data.signals.map(s => {
          const sig = (s.message.match(/Signal: (\\w+)/)||[])[1];
          return `<div class="log-row"><span class="log-time">${s.time.split(' ')[1]||s.time}</span><span>${sig?badgeHTML(sig):''} ${s.message}</span></div>`;
        }).join('');

    // Errors
    const eEl = document.getElementById('errorsList');
    eEl.innerHTML = data.errors.length===0
      ? '<div class="empty-state">NO ERRORS &#8212; ALL CLEAR &#10003;</div>'
      : data.errors.map(e => `<div class="log-row"><span class="log-time">${e.time.split(' ')[1]||e.time}</span><span style="color:#ff4444">${e.message}</span></div>`).join('');

    // Suggestions
    try {
      const sugs  = await (await fetch('/api/suggestions')).json();
      const sugEl = document.getElementById('sugList');
      document.getElementById('sugCount').textContent = sugs.length;
      sugEl.innerHTML = sugs.length === 0
        ? '<div class="empty-state">No suggestions right now — scanning every 30 min during market hours</div>'
        : sugs.map(s => {
            const alreadyAdded = !!levels[s.symbol];
            return `<div class="suggestion-card">
              <div class="sug-info">
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
                  <span class="sug-symbol">${s.symbol}</span>
                  <span class="signal-badge badge-${s.signal}">${s.signal}</span>
                  <span class="sug-price">&#8377;${s.price}</span>
                </div>
                <div class="sug-reason">${s.reason} &nbsp;|&nbsp; S:&#8377;${s.support} &nbsp;R:&#8377;${s.resistance}</div>
              </div>
              <span class="sug-vol ${s.high_volume?'':'low'}">${s.volume_ratio}x vol</span>
              <button class="add-sug-btn ${alreadyAdded?'added':''}"
                onclick="${alreadyAdded?'void(0)':`addFromSuggestion('${s.symbol}',${s.support},${s.resistance})`}"
                ${alreadyAdded?'disabled':''}>
                ${alreadyAdded?'WATCHING':'+ ADD'}
              </button>
            </div>`;
          }).join('');
    } catch(e){ console.error('Suggestions error:', e); }

    // P&L table
    const tbody     = document.getElementById('pnlTableBody');
    const pnlTrades = data.pnl_trades || [];
    tbody.innerHTML = pnlTrades.length===0
      ? '<tr><td colspan="6" style="text-align:center;padding:36px;color:var(--muted);font-size:11px">NO TRADES YET</td></tr>'
      : pnlTrades.map(t => {
          let pnlHTML = '<span class="pnl-pending">OPEN</span>';
          if(t.pnl !== null && t.pnl !== 'closed'){
            const cls = t.pnl >= 0 ? 'pnl-positive' : 'pnl-negative';
            pnlHTML = `<span class="${cls}">${t.pnl>=0?'+':''}&#8377;${t.pnl}</span>`;
          }
          const ac = t.action==='BUY' ? 'var(--buy)' : 'var(--sell)';
          return `<tr>
            <td style="color:var(--muted);font-size:10px">${t.time}</td>
            <td style="font-weight:700">${t.symbol}</td>
            <td><span style="color:${ac};font-weight:700">${t.action}</span></td>
            <td>&#8377;${t.price}</td>
            <td>${t.quantity}</td>
            <td>${pnlHTML}</td>
          </tr>`;
        }).join('');

  } catch(e){ console.error(e); }
}

document.addEventListener('keydown', e => {
  if(e.key === 'Enter' && document.activeElement.classList.contains('form-input')){
    addStock();
  }
});

loadData();
setInterval(loadData, 30000);
</script>
</body>
</html>
"""

@app.route('/')
@login_required
def index():
    return render_template_string(HTML)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
