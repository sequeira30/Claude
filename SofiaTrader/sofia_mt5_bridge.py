import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import os
import time
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

    def connect(self, retries: int = 3, delay: float = 2.0) -> bool:
        for attempt in range(1, retries + 1):
            if not mt5.initialize():
                print(f"[MT5] ✗ initialize() falhou ({attempt}/{retries}): {mt5.last_error()}")
                time.sleep(delay)
                continue
            if not mt5.login(self.ACCOUNT, self.PASSWORD, self.SERVER):
                print(f"[MT5] ✗ login() falhou ({attempt}/{retries}): {mt5.last_error()}")
                mt5.shutdown()
                time.sleep(delay)
                continue
            info = mt5.account_info()
            if not info:
                print(f"[MT5] ✗ account_info() vazio ({attempt}/{retries}): {mt5.last_error()}")
                mt5.shutdown()
                time.sleep(delay)
                continue
            print(f"[MT5] ✓ {info.login} | ${info.balance:.2f} | {self.SERVER}")
            return True
        return False

    def disconnect(self):
        mt5.shutdown()

    def _ensure_symbol(self, symbol: str) -> bool:
        """Garante que o símbolo está visível no Market Watch antes de o usar."""
        info = mt5.symbol_info(symbol)
        if info is None:
            print(f"[MT5] ✗ Símbolo desconhecido: {symbol} | {mt5.last_error()}")
            return False
        if not info.visible and not mt5.symbol_select(symbol, True):
            print(f"[MT5] ✗ Não foi possível selecionar {symbol} | {mt5.last_error()}")
            return False
        return True

    def get_account(self) -> dict:
        i = mt5.account_info()
        return {"login": i.login, "balance": i.balance, "equity": i.equity,
                "margin": i.margin, "free_margin": i.margin_free,
                "profit": i.profit, "leverage": i.leverage} if i else {}

    def get_ohlcv(self, symbol: str, tf: str, bars: int = 500) -> pd.DataFrame:
        if not self._ensure_symbol(symbol):
            return pd.DataFrame()
        rates = mt5.copy_rates_from_pos(symbol, self.TF_MAP.get(tf, mt5.TIMEFRAME_H1), 0, bars)
        if rates is None or len(rates) == 0:
            print(f"[MT5] ✗ Sem OHLCV para {symbol} {tf} | {mt5.last_error()}")
            return pd.DataFrame()
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.set_index("time", inplace=True)
        df.rename(columns={"open":"o","high":"h","low":"l","close":"c","tick_volume":"vol"}, inplace=True)
        return df[["o","h","l","c","vol"]]

    def get_tick(self, symbol: str) -> dict:
        if not self._ensure_symbol(symbol):
            return {}
        t = mt5.symbol_info_tick(symbol)
        info = mt5.symbol_info(symbol)
        if not t or not info:
            return {}
        return {"bid": t.bid, "ask": t.ask,
                "spread": round((t.ask - t.bid) / info.point) if info.point else 0}

    def get_open_positions(self) -> list:
        pos = mt5.positions_get() or []
        return [{"ticket": p.ticket, "symbol": p.symbol,
                 "type": "BUY" if p.type == 0 else "SELL",
                 "volume": p.volume, "open_price": p.price_open,
                 "sl": p.sl, "tp": p.tp, "profit": round(p.profit, 2)} for p in pos]

    def market_order(self, symbol: str, direction: str, lot: float,
                     sl: float = None, tp: float = None,
                     comment: str = "Sofia") -> dict:
        """Abre uma ordem a mercado. sl/tp são níveis de PREÇO absolutos
        (não pips) — calculados pelo motor SMC ou pela IA, que já conhecem
        a escala correta do símbolo (ouro, cripto, forex, índices…)."""
        if not self._ensure_symbol(symbol):
            return {"error": "símbolo indisponível"}
        info = mt5.symbol_info(symbol)
        tick = mt5.symbol_info_tick(symbol)
        if not info or not tick:
            return {"error": "symbol info failed"}

        step = info.volume_step or 0.01
        lot = round(round(lot / step) * step, 2)
        lot = max(info.volume_min, min(lot, info.volume_max))

        otype = mt5.ORDER_TYPE_BUY if direction.upper() == "BUY" else mt5.ORDER_TYPE_SELL
        price = tick.ask if direction.upper() == "BUY" else tick.bid

        req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": lot,
               "type": otype, "price": price,
               "sl": round(sl, info.digits) if sl else 0.0,
               "tp": round(tp, info.digits) if tp else 0.0,
               "deviation": 20, "magic": 202400, "comment": comment,
               "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC}
        r = mt5.order_send(req)
        if r is None:
            return {"error": f"order_send falhou: {mt5.last_error()}"}
        return {"ticket": r.order, "price": r.price, "status": "OK"} \
               if r.retcode == mt5.TRADE_RETCODE_DONE else {"error": r.comment, "retcode": r.retcode}

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
        if r is None:
            return {"error": f"order_send falhou: {mt5.last_error()}"}
        return {"status": "OK" if r.retcode == mt5.TRADE_RETCODE_DONE else "ERRO", "retcode": r.retcode}

    def close_all_positions(self) -> list:
        return [self.close_position(p["ticket"]) for p in self.get_open_positions()]

    def modify_position(self, ticket: int, sl: float, tp: float) -> dict:
        r = mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": ticket, "sl": sl, "tp": tp})
        if r is None:
            return {"error": f"order_send falhou: {mt5.last_error()}"}
        return {"status": "OK" if r.retcode == mt5.TRADE_RETCODE_DONE else "ERRO", "retcode": r.retcode}

    def get_symbol_point(self, symbol: str) -> float:
        info = mt5.symbol_info(symbol)
        return info.point if info else 0.0001

    def calc_lot_size(self, symbol: str, risk_pct: float, sl_distance: float) -> float:
        """Tamanho de lote correto para QUALQUER instrumento (forex, ouro,
        cripto, índices), usando trade_tick_value/trade_tick_size em vez de
        assumir a convenção de 'pip' do forex — essa assunção parte-se em
        XAUUSD e BTCUSD, os pares primários deste sistema."""
        if not self._ensure_symbol(symbol) or sl_distance <= 0:
            return 0.01
        balance = self.get_account().get("balance", 1000)
        risk_amount = balance * (risk_pct / 100)
        info = mt5.symbol_info(symbol)
        if not info:
            return 0.01
        tick_size  = info.trade_tick_size or info.point
        tick_value = info.trade_tick_value or (info.trade_contract_size * tick_size)
        if tick_size <= 0 or tick_value <= 0:
            return info.volume_min
        loss_per_lot = (sl_distance / tick_size) * tick_value
        if loss_per_lot <= 0:
            return info.volume_min
        lot = risk_amount / loss_per_lot
        step = info.volume_step or 0.01
        lot = round(lot / step) * step
        return round(max(info.volume_min, min(lot, info.volume_max)), 2)
