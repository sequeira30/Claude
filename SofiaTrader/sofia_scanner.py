import schedule, time, json
from datetime import datetime, timezone
from sofia_mt5_bridge import SofiaMT5Bridge
from smc_engine import SofiaSmcEngine

PAIRS      = ["XAUUSD","BTCUSD","EURUSD","GBPUSD","USDJPY","US30","NAS100","USDCHF"]
TIMEFRAMES = ["H4","H1","M15"]
MIN_CONF   = 60.0
MIN_QUAL   = ["A+","A"]

class SofiaScanner:

    def __init__(self, bridge: SofiaMT5Bridge):
        self.bridge  = bridge
        self.engine  = SofiaSmcEngine()
        self.signals = []
        self.running = False

    def start(self, interval_minutes: int = 5):
        print(f"[Scanner] ✓ Iniciado | {interval_minutes}min | {len(PAIRS)} pares")
        self.running = True
        schedule.every(interval_minutes).minutes.do(self._scan)
        self._scan()
        while self.running:
            schedule.run_pending()
            time.sleep(1)

    def stop(self):
        self.running = False

    def _scan(self):
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        print(f"\n[Scanner] 🔍 {ts}")
        found = []
        for pair in PAIRS:
            for tf in TIMEFRAMES:
                try:
                    df  = self.bridge.get_ohlcv(pair, tf, 200)
                    ana = self.engine.analyse(df, pair, tf)
                    if (ana.confidence >= MIN_CONF and
                        ana.setup_quality in MIN_QUAL and
                        ana.bias != "NEUTRAL" and
                        ana.order_block is not None):
                        tick = self.bridge.get_tick(pair)
                        found.append({
                            "id":          f"{pair}_{tf}_{int(time.time())}",
                            "ts":          ts,
                            "symbol":      pair,
                            "tf":          tf,
                            "direction":   "BUY" if ana.bias=="BULLISH" else "SELL",
                            "quality":     ana.setup_quality,
                            "confidence":  ana.confidence,
                            "entry_zone":  ana.entry_zone,
                            "sl":          ana.sl_level,
                            "tps":         ana.tp_targets[:3],
                            "ob":          ana.order_block,
                            "fvg":         ana.fvg,
                            "killzone":    ana.killzone,
                            "price":       tick.get("bid",0),
                        })
                        print(f"  ⚡ {pair} {tf} | {ana.bias} | {ana.setup_quality} | {ana.confidence:.0f}%")
                except Exception as e:
                    pass

        self.signals = found
        self._save(found)
        if found:
            self._notify(max(found, key=lambda x: x["confidence"]))
        print(f"[Scanner] ✅ {len(found)} sinais")

    def _save(self, signals):
        import os
        os.makedirs("data", exist_ok=True)
        with open("data/signals.json","w") as f:
            json.dump({"updated": datetime.now(timezone.utc).isoformat(),
                       "count": len(signals), "signals": signals}, f, indent=2, default=str)

    def _notify(self, top):
        try:
            from win10toast import ToastNotifier
            ToastNotifier().show_toast(
                "⚡ Sofia Trading",
                f"{top['symbol']} {top['tf']} {top['direction']} | {top['quality']} | {top['confidence']:.0f}%",
                duration=8, threaded=True)
        except: pass

    def get_best(self) -> dict:
        return max(self.signals, key=lambda x: x["confidence"]) if self.signals else {}
