import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import List
from sofia_mt5_bridge import SofiaMT5Bridge
from smc_engine import SofiaSmcEngine

@dataclass
class Trade:
    symbol:    str;  tf:      str
    direction: str;  entry:   float
    sl:        float; tp:     float
    open_time: str;  close_time: str
    pnl_pips:  float; pnl_pct: float
    outcome:   str   # WIN / LOSS / OPEN

@dataclass
class BacktestResult:
    total_trades:  int;  wins:        int
    losses:        int;  win_rate:    float
    profit_factor: float; sharpe:     float
    max_drawdown:  float; total_return: float
    avg_rr:        float; equity_curve: list
    trades:        List[Trade]

class SofiaBacktester:

    INITIAL_BALANCE = 10_000.0
    RISK_PCT        = 1.0   # % por trade

    def run(self, symbol: str, tf: str, bars: int = 1000,
            bridge: SofiaMT5Bridge = None) -> BacktestResult:
        print(f"[Backtest] {symbol} {tf} | {bars} barras...")
        df = bridge.get_ohlcv(symbol, tf, bars) if bridge else self._synthetic(bars)
        engine  = SofiaSmcEngine()
        trades  = []
        balance = self.INITIAL_BALANCE
        equity  = [balance]

        for i in range(50, len(df) - 10):
            ana = engine.analyse(df.iloc[i-50:i+1], symbol, tf)

            if (ana.confidence < 60 or
                ana.setup_quality not in ["A+","A"] or
                ana.bias == "NEUTRAL" or
                not ana.entry_zone or not ana.sl_level or not ana.tp_targets):
                continue

            entry  = (ana.entry_zone[0] + ana.entry_zone[1]) / 2
            sl     = ana.sl_level
            tp     = ana.tp_targets[0]
            sl_d   = abs(entry - sl)
            tp_d   = abs(tp - entry)
            if sl_d == 0 or tp_d / sl_d < 1.5: continue

            outcome, pips = self._simulate(ana.bias, entry, sl, tp, df.iloc[i+1:i+20])
            risk    = balance * (self.RISK_PCT / 100)
            pnl_amt = risk * (pips / sl_d) if sl_d else 0
            balance += pnl_amt
            equity.append(balance)

            trades.append(Trade(
                symbol=symbol, tf=tf,
                direction="BUY" if ana.bias=="BULLISH" else "SELL",
                entry=round(entry,5), sl=round(sl,5), tp=round(tp,5),
                open_time=str(df.index[i]),
                close_time=str(df.index[min(i+20,len(df)-1)]),
                pnl_pips=round(pips,1),
                pnl_pct=round(pnl_amt/self.INITIAL_BALANCE*100,2),
                outcome=outcome))

        return self._stats(trades, equity)

    def _simulate(self, bias, entry, sl, tp, future):
        for _, row in future.iterrows():
            if bias == "BULLISH":
                if row["l"] <= sl: return "LOSS", -abs(entry-sl)
                if row["h"] >= tp: return "WIN",   abs(tp-entry)
            else:
                if row["h"] >= sl: return "LOSS", -abs(entry-sl)
                if row["l"] <= tp: return "WIN",   abs(tp-entry)
        return "OPEN", 0

    def _stats(self, trades, equity) -> BacktestResult:
        if not trades:
            return BacktestResult(0,0,0,0,0,0,0,0,0,[],[])
        wins   = [t for t in trades if t.outcome=="WIN"]
        losses = [t for t in trades if t.outcome=="LOSS"]
        gp  = sum(t.pnl_pips for t in wins)
        gl  = abs(sum(t.pnl_pips for t in losses))
        pf  = gp / gl if gl else float("inf")
        ret = pd.Series([t.pnl_pct for t in trades])
        sr  = ret.mean()/ret.std()*np.sqrt(252) if ret.std() else 0
        eq  = pd.Series(equity)
        mdd = ((eq.cummax()-eq)/eq.cummax()).max()*100
        tot = (equity[-1]-self.INITIAL_BALANCE)/self.INITIAL_BALANCE*100
        rr  = (gp/len(wins))/(gl/len(losses)) if wins and losses else 0
        return BacktestResult(
            total_trades=len(trades), wins=len(wins), losses=len(losses),
            win_rate=round(len(wins)/len(trades)*100,1),
            profit_factor=round(pf,2), sharpe=round(sr,2),
            max_drawdown=round(mdd,1), total_return=round(tot,1),
            avg_rr=round(rr,2), equity_curve=equity, trades=trades)

    def _synthetic(self, n: int) -> pd.DataFrame:
        np.random.seed(42); price = 2650.0; rows = []
        for _ in range(n):
            o=price; c=o+np.random.normal(0,2)
            h=max(o,c)+abs(np.random.normal(0,1))
            l=min(o,c)-abs(np.random.normal(0,1))
            rows.append({"o":round(o,2),"h":round(h,2),"l":round(l,2),"c":round(c,2),"vol":500})
            price=c
        return pd.DataFrame(rows)

    def print_report(self, r: BacktestResult):
        print(f"""
╔══════════════════════════════════╗
║     SOFIA BACKTEST REPORT        ║
╠══════════════════════════════════╣
║ Trades:    {r.total_trades:>20} ║
║ Win Rate:  {r.win_rate:>19.1f}% ║
║ PF:        {r.profit_factor:>20.2f} ║
║ Sharpe:    {r.sharpe:>20.2f} ║
║ Max DD:    {r.max_drawdown:>19.1f}% ║
║ Return:    {r.total_return:>19.1f}% ║
║ Avg R:R:   {r.avg_rr:>19.2f}R ║
╚══════════════════════════════════╝""")

# Uso
if __name__ == "__main__":
    bridge = SofiaMT5Bridge()
    bridge.connect()
    bt = SofiaBacktester()
    r  = bt.run("XAUUSD","H1",bars=500,bridge=bridge)
    bt.print_report(r)
    bridge.disconnect()
