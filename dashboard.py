from flask import Flask, jsonify, render_template_string
import os, re
from datetime import datetime

app = Flask(__name__)

LOG_FILE = "bot_log.txt"
STOCKS   = ["INFY", "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK"]

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
    prices, latest_signals = {}, {}
    for s in signals:
        for stock in STOCKS:
            if stock in s["message"] and stock not in prices:
                price_match = re.search(r'[\u20b9]([\d.]+)', s["message"])
                sig_match   = re.search(r'Signal: (\w+)', s["message"])
                if price_match:
                    prices[stock]         = price_match.group(1)
                    latest_signals[stock] = sig_match.group(1) if sig_match else "HOLD"
    return prices, latest_signals

def get_bot_status():
    if not os.path.exists(LOG_FILE):
        return "UNKNOWN"
    diff = (datetime.now() - datetime.fromtimestamp(os.path.getmtime(LOG_FILE))).seconds
    return "RUNNING" if diff < 400 else "STOPPED"

HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Multi-Stock Trading Dashboard</title>
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
  .stocks-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:28px}
  .stock-card{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:16px;position:relative;overflow:hidden;transition:border-color 0.3s}
  .stock-card::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:var(--muted);transition:background 0.3s}
  .stock-card.BUY::before{background:var(--buy)}
  .stock-card.SELL::before{background:var(--sell)}
  .stock-card.HOLD::before{background:var(--hold)}
  .stock-card.STOP_LOSS::before{background:var(--stop)}
  .stock-symbol{font-family:'Syne',sans-serif;font-size:15px;font-weight:800;margin-bottom:6px}
  .stock-price{font-size:20px;font-weight:700;color:var(--accent);margin-bottom:8px}
  .stock-price.no-data{font-size:14px;color:var(--muted)}
  .signal-badge{display:inline-block;padding:2px 10px;border-radius:4px;font-size:10px;font-weight:700;letter-spacing:1px}
  .badge-BUY{background:rgba(0,255,136,0.15);color:var(--buy);border:1px solid rgba(0,255,136,0.3)}
  .badge-SELL{background:rgba(255,68,68,0.15);color:var(--sell);border:1px solid rgba(255,68,68,0.3)}
  .badge-HOLD{background:rgba(77,166,255,0.15);color:var(--hold);border:1px solid rgba(77,166,255,0.3)}
  .badge-STOP_LOSS{background:rgba(255,107,53,0.15);color:var(--stop);border:1px solid rgba(255,107,53,0.3)}
  .badge-WAITING{background:rgba(74,85,104,0.15);color:var(--muted);border:1px solid rgba(74,85,104,0.3)}
  .stats-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:28px}
  .stat-card{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:18px 20px}
  .stat-label{font-size:10px;letter-spacing:2px;text-transform:uppercase;color:var(--muted);margin-bottom:8px}
  .stat-value{font-family:'Syne',sans-serif;font-size:26px;font-weight:800;color:var(--accent)}
  .stat-card.red .stat-value{color:var(--sell)}
  .stat-card.blue .stat-value{color:var(--accent3)}
  .stat-card.orange .stat-value{color:var(--stop)}
  .status-bar{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:14px 24px;margin-bottom:24px;display:flex;align-items:center;gap:24px;font-size:12px}
  .status-item{display:flex;align-items:center;gap:8px}
  .status-dot{width:6px;height:6px;border-radius:50%}
  .status-dot.green{background:var(--accent);box-shadow:0 0 8px var(--accent)}
  .status-dot.red{background:var(--sell)}
  .status-dot.grey{background:var(--muted)}
  .status-label{color:var(--muted);font-size:10px;letter-spacing:1px;text-transform:uppercase}
  .status-value{font-weight:700}
  .main-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:20px}
  .panel{background:var(--surface);border:1px solid var(--border);border-radius:8px;overflow:hidden}
  .panel-header{padding:14px 20px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between}
  .panel-title{font-size:10px;letter-spacing:2px;text-transform:uppercase;color:var(--muted)}
  .panel-count{font-size:11px;color:var(--accent);background:rgba(0,255,136,0.1);padding:2px 8px;border-radius:20px}
  .panel-body{padding:12px 20px;max-height:300px;overflow-y:auto}
  .panel-body::-webkit-scrollbar{width:4px}
  .panel-body::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}
  .log-row{display:flex;gap:12px;padding:9px 0;border-bottom:1px solid rgba(30,45,61,0.5);font-size:12px}
  .log-row:last-child{border-bottom:none}
  .log-time{color:var(--muted);white-space:nowrap;flex-shrink:0;font-size:10px}
  .full-panel{grid-column:1/-1}
  .empty-state{text-align:center;padding:36px 20px;color:var(--muted);font-size:11px;letter-spacing:1px}
  .refresh-btn{background:transparent;border:1px solid var(--border);color:var(--muted);padding:6px 16px;border-radius:4px;font-family:'Space Mono',monospace;font-size:11px;letter-spacing:1px;cursor:pointer;transition:all 0.2s}
  .refresh-btn:hover{border-color:var(--accent);color:var(--accent)}
  @media(max-width:900px){.stocks-grid{grid-template-columns:repeat(3,1fr)}.stats-grid{grid-template-columns:repeat(2,1fr)}.main-grid{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="container">
  <header>
    <div class="logo">MULTI-STOCK <span>TRADE BOT</span></div>
    <div style="display:flex;align-items:center;gap:16px">
      <button class="refresh-btn" onclick="loadData()">↻ REFRESH</button>
      <div class="live-badge"><div class="pulse" id="statusPulse"></div><span id="statusText">CHECKING...</span></div>
    </div>
  </header>

  <div class="stocks-grid">
    <div class="stock-card" id="card-INFY"><div class="stock-symbol">INFY</div><div class="stock-price no-data">Loading...</div></div>
    <div class="stock-card" id="card-RELIANCE"><div class="stock-symbol">RELIANCE</div><div class="stock-price no-data">Loading...</div></div>
    <div class="stock-card" id="card-TCS"><div class="stock-symbol">TCS</div><div class="stock-price no-data">Loading...</div></div>
    <div class="stock-card" id="card-HDFCBANK"><div class="stock-symbol">HDFCBANK</div><div class="stock-price no-data">Loading...</div></div>
    <div class="stock-card" id="card-ICICIBANK"><div class="stock-symbol">ICICIBANK</div><div class="stock-price no-data">Loading...</div></div>
  </div>

  <div class="stats-grid">
    <div class="stat-card"><div class="stat-label">Total Signals</div><div class="stat-value" id="totalSignals">0</div></div>
    <div class="stat-card red"><div class="stat-label">Total Trades</div><div class="stat-value" id="totalTrades">0</div></div>
    <div class="stat-card blue"><div class="stat-label">Stocks Watched</div><div class="stat-value">5</div></div>
    <div class="stat-card orange"><div class="stat-label">Errors</div><div class="stat-value" id="totalErrors">0</div></div>
  </div>

  <div class="status-bar">
    <div class="status-item"><div class="status-dot" id="botDot"></div><span class="status-label">Bot</span><span class="status-value" id="botStatus">—</span></div>
    <div class="status-item"><div class="status-dot" id="marketDot"></div><span class="status-label">Market</span><span class="status-value" id="marketStatus">—</span></div>
    <div class="status-item"><span class="status-label">Last Updated</span><span class="status-value" id="lastUpdated">—</span></div>
  </div>

  <div class="main-grid">
    <div class="panel">
      <div class="panel-header"><span class="panel-title">Recent Trades</span><span class="panel-count" id="tradeCount">0</span></div>
      <div class="panel-body" id="tradesList"><div class="empty-state">NO TRADES YET</div></div>
    </div>
    <div class="panel">
      <div class="panel-header"><span class="panel-title">Signal History</span><span class="panel-count" id="signalCount">0</span></div>
      <div class="panel-body" id="signalsList"><div class="empty-state">NO SIGNALS YET</div></div>
    </div>
    <div class="panel full-panel">
      <div class="panel-header"><span class="panel-title">Error Log</span><span class="panel-count" id="errorCount">0</span></div>
      <div class="panel-body" id="errorsList"><div class="empty-state">NO ERRORS — ALL CLEAR ✓</div></div>
    </div>
  </div>
</div>

<script>
const STOCKS = ["INFY","RELIANCE","TCS","HDFCBANK","ICICIBANK"];
function isMarketOpen(){const n=new Date(),d=n.getDay();if(d===0||d===6)return false;const m=n.getHours()*60+n.getMinutes();return m>=9*60+15&&m<=15*60+30}
function badgeHTML(s){return`<span class="signal-badge badge-${s||'WAITING'}">${s||'WAITING'}</span>`}
async function loadData(){
  try{
    const data=await (await fetch('/api/data')).json();
    const running=data.status==='RUNNING';
    document.getElementById('statusPulse').className='pulse'+(running?'':' stopped');
    document.getElementById('statusText').textContent=running?'BOT LIVE':'BOT STOPPED';
    document.getElementById('botDot').className='status-dot '+(running?'green':'red');
    document.getElementById('botStatus').textContent=data.status;
    const mkt=isMarketOpen();
    document.getElementById('marketDot').className='status-dot '+(mkt?'green':'grey');
    document.getElementById('marketStatus').textContent=mkt?'OPEN':'CLOSED';
    document.getElementById('lastUpdated').textContent=new Date().toLocaleTimeString();
    document.getElementById('totalSignals').textContent=data.signals.length;
    document.getElementById('totalTrades').textContent=data.trades.length;
    document.getElementById('totalErrors').textContent=data.errors.length;
    document.getElementById('tradeCount').textContent=data.trades.length;
    document.getElementById('signalCount').textContent=data.signals.length;
    document.getElementById('errorCount').textContent=data.errors.length;
    const prices=data.prices||{},sigs=data.latest_signals||{};
    STOCKS.forEach(s=>{
      const c=document.getElementById('card-'+s);
      const p=prices[s],sig=sigs[s];
      if(c)c.innerHTML=`<div class="stock-symbol">${s}</div><div class="stock-price ${p?'':'no-data'}">${p?'&#8377;'+p:'&#8212;'}</div>${badgeHTML(sig)}`;
      if(c)c.className='stock-card '+(sig||'');
    });
    const tEl=document.getElementById('tradesList');
    tEl.innerHTML=data.trades.length===0?'<div class="empty-state">NO TRADES YET</div>':data.trades.map(t=>`<div class="log-row"><span class="log-time">${t.time.split(' ')[1]||t.time}</span><span>${t.message}</span></div>`).join('');
    const sEl=document.getElementById('signalsList');
    sEl.innerHTML=data.signals.length===0?'<div class="empty-state">NO SIGNALS YET</div>':data.signals.map(s=>{const sig=(s.message.match(/Signal: (\w+)/)||[])[1];return`<div class="log-row"><span class="log-time">${s.time.split(' ')[1]||s.time}</span><span>${sig?badgeHTML(sig):''} ${s.message}</span></div>`}).join('');
    const eEl=document.getElementById('errorsList');
    eEl.innerHTML=data.errors.length===0?'<div class="empty-state">NO ERRORS &#8212; ALL CLEAR &#10003;</div>':data.errors.map(e=>`<div class="log-row"><span class="log-time">${e.time.split(' ')[1]||e.time}</span><span style="color:#ff4444">${e.message}</span></div>`).join('');
  }catch(e){console.error(e)}
}
loadData();
setInterval(loadData,30000);
</script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML)

@app.route('/api/data')
def api_data():
    trades, signals, errors = parse_logs()
    prices, latest_signals  = get_latest_prices(signals)
    return jsonify({
        "status":         get_bot_status(),
        "trades":         trades,
        "signals":        signals,
        "errors":         errors,
        "prices":         prices,
        "latest_signals": latest_signals
    })

if __name__ == '__main__':
    app.run(debug=False, port=5000)
