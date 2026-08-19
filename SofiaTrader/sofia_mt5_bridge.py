import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import os
from dotenv import load_dotenv

load_dotenv()

class SofiaMT5Bridge:

    ACCOUNT  = int(os.getenv("MT5_ACCOUNT", "1729484"))
    PASSWORD = os.getenv("MT5_PASSWORD", "")
    SERVER   = os.getenv("MT5_SERVER", "PUPrime-Live")

    TF_MAP = {
        "M1": mt5.TIMEFRAME_M1,  "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,"M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,  "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,  "W1": mt5.TIMEFRAME_W1,
    }

    def connect(self) -> bool:
        if not mt5.initialize():
            return False
        if not mt5.login(self.ACCOUNT, self.PASSWORD, self.SERVER):
            return False
        info = mt5.account_info()
        print(f"[MT5] ✓ {info.login} | ${info.balance:.2f}")
        return True

    def disconnect(self):
        mt5.shutdown()

    def get_account(self) -> dict:
        i = mt5.account_info()
        return {"login": i.login, "balance": i.balance, "equity": i.equity,
                "margin": i.margin, "free_margin": i.margin_free,
                "profit": i.profit, "leverage": i.leverage} if i else {}

    def get_ohlcv(self, symbol: str, tf: str, bars: int = 500) -> pd.DataFrame:
        rates = mt5.copy_rates_from_pos(symbol, self.TF_MAP.get(tf, mt5.TIMEFRAME_H1), 0, bars)
        if rates is None:
            return pd.DataFrame()
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.set_index("time", inplace=True)
        df.rename(columns={"open":"o","high":"h","low":"l","close":"c","tick_volume":"vol"}, inplace=True)
        return df[["o","h","l","c","vol"]]

    def get_tick(self, symbol: str) -> dict:
        t = mt5.symbol_info_tick(symbol)
        return {"bid": t.bid, "ask": t.ask,
                "spread": round((t.ask - t.bid) * 10000, 1)} if t else {}

    def get_open_positions(self) -> list:
        pos = mt5.positions_get() or []
        return [{"ticket": p.ticket, "symbol": p.symbol,
                 "type": "BUY" if p.type == 0 else "SELL",
                 "volume": p.volume, "open_price": p.price_open,
                 "sl": p.sl, "tp": p.tp, "profit": round(p.profit, 2)} for p in pos]

    def market_order(self, symbol: str, direction: str, lot: float,
                     sl_pips: float = 20, tp_pips: float = 60,
                     comment: str = "Sofia") -> dict:
        info = mt5.symbol_info(symbol)
        tick = mt5.symbol_info_tick(symbol)
        if not info or not tick:
            return {"error": "symbol info failed"}
        point = info.point
        otype = mt5.ORDER_TYPE_BUY if direction.upper() == "BUY" else mt5.ORDER_TYPE_SELL
        price = tick.ask if direction.upper() == "BUY" else tick.bid
        sl = price - sl_pips * point * 10 if direction.upper() == "BUY" else price + sl_pips * point * 10
        tp = price + tp_pips * point * 10 if direction.upper() == "BUY" else price - tp_pips * point * 10
        req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": lot,
               "type": otype, "price": price, "sl": sl, "tp": tp,
               "deviation": 20, "magic": 202400, "comment": comment,
               "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC}
        r = mt5.order_send(req)
        return {"ticket": r.order, "price": r.price, "status": "OK"} \
               if r.retcode == mt5.TRADE_RETCODE_DONE else {"error": r.comment}

    def close_position(self, ticket: int) -> dict:
        pos = mt5.positions_get(ticket=ticket)
        if not pos:
            return {"error": "not found"}
        p = pos[0]
        tick = mt5.symbol_info_tick(p.symbol)
        price = tick.bid if p.type == 0 else tick.ask
        req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": p.symbol,
               "volume": p.volume, "type": mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY,
               "position": ticket, "price": price, "deviation": 20,
               "magic": 202400, "comment": "Sofia Close",
               "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC}
        r = mt5.order_send(req)
        return {"status": "OK" if r.retcode == mt5.TRADE_RETCODE_DONE else "ERRO"}

    def modify_position(self, ticket: int, sl: float, tp: float) -> dict:
        r = mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": ticket, "sl": sl, "tp": tp})
        return {"status": "OK" if r.retcode == mt5.TRADE_RETCODE_DONE else "ERRO"}

    def calc_lot_size(self, symbol: str, risk_pct: float, sl_pips: float) -> float:
        balance = self.get_account().get("balance", 1000)
        risk_amount = balance * (risk_pct / 100)
        info = mt5.symbol_info(symbol)
        if not info:
            return 0.01
        pip_value = info.trade_contract_size * info.point * 10
        lot = round(risk_amount / (sl_pips * pip_value), 2)
        return max(info.volume_min, min(lot, info.volume_max))
