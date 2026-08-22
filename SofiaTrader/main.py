import schedule, time, json, threading
from datetime import datetime, timezone

from sofia_mt5_bridge   import SofiaMT5Bridge
from smc_engine          import SofiaSmcEngine
from sofia_ollama_agent  import SofiaOllamaAgent
from sofia_scanner       import SofiaScanner
from sofia_risk_manager  import SofiaRiskManager
from sofia_news_filter   import SofiaNewsFilter

# ─── CONFIG ────────────────────────────────────────────────────────────────────
AUTO_EXECUTE  = False           # True = executa ordens automaticamente
PAIRS_PRIMARY = ["XAUUSD","BTCUSD"]
SCAN_INTERVAL = 5               # minutos entre scans

# ─── INIT ──────────────────────────────────────────────────────────────────────
bridge  = SofiaMT5Bridge()
engine  = SofiaSmcEngine()
agent   = SofiaOllamaAgent()
scanner = SofiaScanner(bridge)
risk    = SofiaRiskManager(bridge)
news    = SofiaNewsFilter()

def log(msg, lvl="INFO"):
    icons = {"INFO":"ℹ️","OK":"✅","WARN":"⚠️","ERR":"❌","TRADE":"💹"}
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {icons.get(lvl,'•')} {msg}")

# ─── CICLO PRINCIPAL ───────────────────────────────────────────────────────────
def cycle():
    log("Ciclo iniciado")

    # 1. Gerir posições já abertas (BE + trailing) — deve correr sempre,
    #    mesmo durante um blackout de notícias ou limite de risco atingido;
    #    isso só bloqueia ABRIR novas posições, não proteger as existentes.
    risk.manage_all()

    # 2. Notícias — bloqueia novas entradas perto de eventos de alto impacto
    blocked, ev = news.is_blocked()
    if blocked:
        log(f"Bloqueado: {ev['event']} em {ev['mins_to']}min","WARN")
        return

    # 3. Risco global
    can, msg = risk.can_trade()
    if not can:
        log(msg, "WARN"); return

    # 4. Scan pares primários
    for pair in PAIRS_PRIMARY:
        try:
            df  = bridge.get_ohlcv(pair, "H1", 200)
            ana = engine.analyse(df, pair, "H1")

            if ana.confidence < 70 or ana.setup_quality not in ["A+","A"]:
                continue

            log(f"{pair} | {ana.bias} | {ana.setup_quality} | {ana.confidence:.0f}%","OK")

            if AUTO_EXECUTE:
                acc  = bridge.get_account()
                tick = bridge.get_tick(pair)
                dec  = agent.decide_trade(
                    ana, acc["balance"],
                    news_upcoming=bool(news.next_event()),
                    spread=tick.get("spread",0)
                )
                if dec.action in ["BUY","SELL"] and dec.confidence >= 70:
                    can2, _ = risk.can_trade_symbol(pair)
                    if can2:
                        lot    = risk.calc_lot(pair, dec.sl, dec.entry)
                        result = bridge.market_order(pair, dec.action, lot,
                                                     sl=dec.sl, tp=dec.tp1,
                                                     comment="Sofia-Auto")
                        log(f"ORDEM: {pair} {dec.action} {lot}L SL:{dec.sl} TP:{dec.tp1} | {result}","TRADE")
                        _log_trade(pair, dec, result)
            else:
                log(f"[MANUAL] Setup encontrado — ver dashboard","INFO")

        except Exception as e:
            log(f"Erro em {pair}: {e}","ERR")

def _log_trade(symbol, dec, result):
    import os; os.makedirs("data", exist_ok=True)
    try:
        with open("data/trades_log.json") as f: log_data = json.load(f)
    except: log_data = []
    log_data.append({"time": datetime.now(timezone.utc).isoformat(),
                     "symbol": symbol, "action": dec.action,
                     "lot": dec.lot_size, "entry": dec.entry,
                     "sl": dec.sl, "reasoning": dec.reasoning,
                     "result": result})
    with open("data/trades_log.json","w") as f:
        json.dump(log_data, f, indent=2, default=str)

def run_server():
    import uvicorn
    from sofia_server import app
    uvicorn.run(app, host="0.0.0.0", port=8080)

# ─── ARRANQUE ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("""
╔═══════════════════════════════════════════╗
║     SOFIA TRADING COMMAND CENTER  v1.0   ║
║   SMC/ICT · Ollama · MT5 PUPrime #1729484║
╚═══════════════════════════════════════════╝""")

    if not bridge.connect():
        log("Falha MT5!","ERR"); exit(1)

    news.refresh()
    log(f"Auto-execute: {'LIGADO' if AUTO_EXECUTE else 'DESLIGADO'}","INFO")

    # Dashboard web em thread separada
    threading.Thread(target=run_server, daemon=True).start()
    log("Dashboard → http://localhost:8080","OK")

    # Agendador
    schedule.every(SCAN_INTERVAL).minutes.do(cycle)
    schedule.every().day.at("00:01").do(risk.reset_daily)
    schedule.every().monday.at("00:02").do(risk.reset_weekly)
    schedule.every().hour.do(news.refresh)

    cycle()  # Execução imediata
    while True:
        schedule.run_pending()
        time.sleep(1)
