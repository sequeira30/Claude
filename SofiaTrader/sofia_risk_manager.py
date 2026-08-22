import json
from datetime import datetime, timezone
from sofia_mt5_bridge import SofiaMT5Bridge

class SofiaRiskManager:

    MAX_RISK_PCT   = 1.0   # % saldo por trade
    MAX_DAY_DD     = 3.0   # % drawdown diário
    MAX_WEEK_DD    = 8.0   # % drawdown semanal
    MAX_TRADES     = 3     # trades abertos em simultâneo
    MAX_PER_SYMBOL = 1     # trades por símbolo
    BE_TRIGGER_RR  = 1.0   # R para move para BE
    TRAIL_START_RR = 1.5   # R para iniciar trailing
    TRAIL_PIPS     = 10    # pips de step trailing

    def __init__(self, bridge: SofiaMT5Bridge):
        self.bridge = bridge
        self._load_stats()

    def _load_stats(self):
        try:
            with open("data/risk_stats.json") as f:
                s = json.load(f)
                self.day_start  = s.get("day_start_balance")
                self.week_start = s.get("week_start_balance")
        except:
            bal = self.bridge.get_account().get("balance", 0)
            self.day_start = self.week_start = bal
            self._save_stats()

    def _save_stats(self):
        import os; os.makedirs("data", exist_ok=True)
        with open("data/risk_stats.json","w") as f:
            json.dump({"day_start_balance": self.day_start,
                       "week_start_balance": self.week_start,
                       "updated": datetime.now(timezone.utc).isoformat()}, f)

    def can_trade(self) -> tuple[bool, str]:
        acc = self.bridge.get_account()
        eq  = acc.get("equity", 0)
        pos = self.bridge.get_open_positions()

        if self.day_start:
            dd = (self.day_start - eq) / self.day_start * 100
            if dd >= self.MAX_DAY_DD:
                return False, f"❌ DD diário {dd:.1f}% ≥ {self.MAX_DAY_DD}%"

        if self.week_start:
            ddw = (self.week_start - eq) / self.week_start * 100
            if ddw >= self.MAX_WEEK_DD:
                return False, f"❌ DD semanal {ddw:.1f}% ≥ {self.MAX_WEEK_DD}%"

        if len(pos) >= self.MAX_TRADES:
            return False, f"❌ Máximo {self.MAX_TRADES} trades atingido"

        return True, "✓ Trading permitido"

    def can_trade_symbol(self, symbol: str) -> tuple[bool, str]:
        pos = [p for p in self.bridge.get_open_positions() if p["symbol"] == symbol]
        if len(pos) >= self.MAX_PER_SYMBOL:
            return False, f"❌ Já existe posição em {symbol}"
        return True, "✓ OK"

    def calc_lot(self, symbol: str, sl_price: float, entry_price: float) -> float:
        sl_dist = abs(entry_price - sl_price)
        if sl_dist == 0:
            return 0.01
        # Delega no bridge: usa trade_tick_value/trade_tick_size do símbolo,
        # correto para qualquer instrumento (não só XAUUSD).
        return self.bridge.calc_lot_size(symbol, self.MAX_RISK_PCT, sl_dist)

    def manage_all(self):
        """Chamar periodicamente — gere BE e trailing em todas as posições"""
        for pos in self.bridge.get_open_positions():
            self._manage_one(pos)

    def _manage_one(self, pos: dict):
        ticket   = pos["ticket"]
        entry    = pos["open_price"]
        sl       = pos["sl"]
        tp       = pos["tp"]
        direction = pos["type"]
        symbol   = pos["symbol"]

        tick = self.bridge.get_tick(symbol)
        if not tick: return
        current = tick["bid"] if direction == "BUY" else tick["ask"]
        point   = self.bridge.get_symbol_point(symbol)

        if not sl or abs(entry - sl) < point: return
        sl_dist     = abs(entry - sl)
        profit_dist = abs(current - entry) if direction == "BUY" else abs(entry - current)
        rr          = profit_dist / sl_dist

        # Break-even: pequena margem de 10 points do próprio símbolo
        # (não um valor fixo de forex — isso partia-se em XAUUSD/BTCUSD)
        buffer = point * 10
        if rr >= self.BE_TRIGGER_RR:
            be = entry + buffer if direction == "BUY" else entry - buffer
            if (direction == "BUY"  and sl < be) or \
               (direction == "SELL" and sl > be):
                self.bridge.modify_position(ticket, sl=be, tp=tp)
                print(f"[Risk] BE → {symbol} #{ticket}")

        # Trailing stop: distância também escalada pelo point do símbolo
        if rr >= self.TRAIL_START_RR:
            trail = self.TRAIL_PIPS * point * 10
            digits = 2 if point >= 0.001 else 5
            new_sl = round(current - trail, digits) if direction == "BUY" \
                     else round(current + trail, digits)
            if (direction == "BUY"  and new_sl > sl) or \
               (direction == "SELL" and new_sl < sl):
                self.bridge.modify_position(ticket, sl=new_sl, tp=tp)
                print(f"[Risk] Trailing → {symbol} #{ticket} SL:{new_sl}")

    def report(self) -> dict:
        acc = self.bridge.get_account()
        pos = self.bridge.get_open_positions()
        bal = acc.get("balance", 0)
        eq  = acc.get("equity", 0)
        dd  = (self.day_start - eq) / self.day_start * 100 if self.day_start else 0
        ok, msg = self.can_trade()
        return {"balance": bal, "equity": eq,
                "day_dd_pct": round(dd, 2), "max_day_dd": self.MAX_DAY_DD,
                "open_trades": len(pos), "max_trades": self.MAX_TRADES,
                "total_pnl": round(sum(p["profit"] for p in pos), 2),
                "can_trade": ok, "status": msg}

    def reset_daily(self):
        self.day_start = self.bridge.get_account().get("balance", 0)
        self._save_stats()
        print(f"[Risk] Stats diárias reset | ${self.day_start:.2f}")

    def reset_weekly(self):
        self.week_start = self.bridge.get_account().get("balance", 0)
        self._save_stats()
        print(f"[Risk] Stats semanais reset | ${self.week_start:.2f}")
