# Sofia Trading Command Center

Automated SMC/ICT trading system for MetaTrader 5 (PUPrime live account #1729484), with a local Ollama
decision agent, a market scanner, risk management, a news filter, a backtester, and a live web dashboard.

This is a **Windows-only** system: the `MetaTrader5` Python package only works against a running MT5
terminal on Windows, so `main.py` must be run on the Windows machine where MT5 is installed and logged
in — not in a Linux/CI environment.

## Architecture

```
main.py                  orchestrator: news -> risk -> SMC scan -> Ollama decision -> MT5 execution
sofia_mt5_bridge.py       MT5 connection, OHLCV, orders, positions, lot sizing
smc_engine.py             SMC/ICT analysis: BOS, CHoCH, Order Blocks, FVG, Liquidity, Killzones
sofia_ollama_agent.py     local LLM (Ollama) trade decisions + chat
sofia_scanner.py          multi-pair / multi-timeframe scanner -> data/signals.json
sofia_server.py           FastAPI + WebSocket server for the dashboard (static/index.html)
sofia_risk_manager.py     break-even, trailing stop, drawdown limits, position sizing
sofia_news_filter.py      ForexFactory high-impact news blackout window
sofia_backtester.py       historical SMC/ICT strategy backtest
static/index.html         live dashboard (ticks, positions, signals, analysis, AI chat, order entry)
data/                     runtime state (signals.json, risk_stats.json, news_events.json, trades_log.json)
```

## Setup (on your Windows PC, with MT5 installed and logged in)

```bat
cd C:\Users\User\Desktop\SofiaTrader
pip install -r requirements.txt --break-system-packages
copy .env.example .env
notepad .env
```

Fill in `.env`:

```env
MT5_ACCOUNT=1729484
MT5_SERVER=PUPrime-Live
MT5_PASSWORD=your_real_password
```

Pull an Ollama model (Ollama must be running on `localhost:11434`):

```bat
ollama pull deepseek-r1:7b
```

## Run

```bat
cd C:\Users\User\Desktop\SofiaTrader
python main.py
```

This connects to MT5, starts the dashboard at **http://localhost:8080**, and starts the 5-minute
scan/decision loop. By default `AUTO_EXECUTE = False` in `main.py` — Sofia only alerts on A/A+ setups
via the dashboard; she does not place trades automatically. Set `AUTO_EXECUTE = True` to let her
execute trades within the risk manager's limits.

Run just the dashboard/API without the orchestration loop:

```bat
python sofia_server.py
```

Run a historical backtest:

```bat
python sofia_backtester.py
```

## Risk defaults (`sofia_risk_manager.py`)

| Rule | Value |
|---|---|
| Max risk per trade | 1% of balance |
| Max daily drawdown | 3% |
| Max weekly drawdown | 8% |
| Max simultaneous trades | 3 |
| Max trades per symbol | 1 |
| Break-even trigger | 1R profit |
| Trailing stop start | 1.5R profit |

## Notes

- `.env` is git-ignored — never commit real MT5 credentials.
- `data/*.json` is git-ignored (runtime state); `data/.gitkeep` keeps the folder in git.
- This system trades a live account. Test on a demo account first, and keep `AUTO_EXECUTE = False`
  until you've validated the setup quality and risk limits match your expectations.
