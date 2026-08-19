from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import asyncio, json, threading, os
from datetime import datetime, timezone

from sofia_mt5_bridge import SofiaMT5Bridge
from smc_engine import SofiaSmcEngine
from sofia_ollama_agent import SofiaOllamaAgent
from sofia_scanner import SofiaScanner

app = FastAPI(title="Sofia Trading Command Center")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="static"), name="static")

bridge  = SofiaMT5Bridge()
engine  = SofiaSmcEngine()
agent   = SofiaOllamaAgent()
scanner = SofiaScanner(bridge)
clients = set()

@app.get("/")
async def root():
    with open("static/index.html") as f:
        return HTMLResponse(f.read())

@app.get("/api/account")
async def account():
    return bridge.get_account()

@app.get("/api/positions")
async def positions():
    return bridge.get_open_positions()

@app.get("/api/tick/{symbol}")
async def tick(symbol: str):
    return bridge.get_tick(symbol)

@app.get("/api/ohlcv/{symbol}/{tf}")
async def ohlcv(symbol: str, tf: str, bars: int = 200):
    df = bridge.get_ohlcv(symbol, tf, bars)
    return df.reset_index().to_dict(orient="records") if not df.empty else []

@app.get("/api/analyse/{symbol}/{tf}")
async def analyse(symbol: str, tf: str):
    df = bridge.get_ohlcv(symbol, tf, 200)
    r  = engine.analyse(df, symbol, tf)
    return {"symbol":r.symbol,"tf":r.timeframe,"bias":r.bias,"bos":r.bos,
            "choch":r.choch,"order_block":r.order_block,"fvg":r.fvg,
            "liquidity":r.liquidity,"killzone":r.killzone,"confidence":r.confidence,
            "entry_zone":r.entry_zone,"sl":r.sl_level,"tps":r.tp_targets,
            "quality":r.setup_quality,"summary":r.summary}

@app.get("/api/signals")
async def signals():
    try:
        with open("data/signals.json") as f: return json.load(f)
    except: return {"signals":[],"count":0}

@app.post("/api/ai/decide/{symbol}/{tf}")
async def ai_decide(symbol: str, tf: str):
    df  = bridge.get_ohlcv(symbol, tf, 200)
    ana = engine.analyse(df, symbol, tf)
    acc = bridge.get_account()
    dec = agent.decide_trade(ana, acc.get("balance",1000))
    return {"action":dec.action,"confidence":dec.confidence,"lot":dec.lot_size,
            "entry":dec.entry,"sl":dec.sl,"tp1":dec.tp1,"tp2":dec.tp2,"tp3":dec.tp3,
            "reasoning":dec.reasoning,"rr":dec.risk_reward}

@app.post("/api/trade/open")
async def open_trade(body: dict):
    result = bridge.market_order(
        body["symbol"], body["direction"], float(body.get("lot",0.01)),
        float(body.get("sl_pips",20)), float(body.get("tp_pips",60)), "Sofia-Web")
    await _broadcast({"type":"trade_opened","data":result})
    return result

@app.post("/api/trade/close/{ticket}")
async def close_trade(ticket: int):
    return bridge.close_position(ticket)

@app.get("/api/ai/chat")
async def ai_chat(msg: str):
    return {"response": agent.chat(msg)}

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    try:
        while True:
            data = await ws.receive_text()
            if json.loads(data).get("type") == "ping":
                await ws.send_json({"type":"pong"})
    except WebSocketDisconnect:
        clients.discard(ws)

async def _broadcast(msg: dict):
    dead = set()
    for c in clients:
        try: await c.send_json(msg)
        except: dead.add(c)
    clients.difference_update(dead)

async def _live_ticker():
    symbols = ["XAUUSD","BTCUSD","EURUSD","GBPUSD","US30"]
    while True:
        if clients:
            ticks = {s: bridge.get_tick(s) for s in symbols}
            await _broadcast({"type":"ticks","data":ticks,
                              "ts": datetime.now(timezone.utc).isoformat()})
        await asyncio.sleep(1)

@app.on_event("startup")
async def startup():
    bridge.connect()
    asyncio.create_task(_live_ticker())
    threading.Thread(target=scanner.start, args=(5,), daemon=True).start()
    print("[Server] ✓ http://localhost:8080")

@app.on_event("shutdown")
async def shutdown():
    bridge.disconnect()
    scanner.stop()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
