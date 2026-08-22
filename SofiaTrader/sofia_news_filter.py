import feedparser
from datetime import datetime, timezone, timedelta
from typing import Optional
import json, os, time

class SofiaNewsFilter:

    FF_RSS = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"

    BLOCK_BEFORE = 30   # minutos antes
    BLOCK_AFTER  = 30   # minutos depois

    HIGH_IMPACT_KEYWORDS = [
        "Non-Farm Payrolls","NFP","CPI","Core CPI","Fed Interest Rate",
        "FOMC","GDP","Unemployment Rate","PCE","Retail Sales",
        "ISM Manufacturing","PMI","PPI","ADP Non-Farm","Consumer Confidence",
    ]

    SYMBOL_CURRENCIES = {
        "XAUUSD": ["USD"], "BTCUSD": ["USD"],
        "EURUSD": ["EUR","USD"], "GBPUSD": ["GBP","USD"],
        "USDJPY": ["USD","JPY"], "USDCHF": ["USD","CHF"],
        "US30":   ["USD"], "NAS100": ["USD"],
    }

    def __init__(self):
        self.events = []
        self._refresh_ts = None

    def refresh(self):
        try:
            feed = feedparser.parse(self.FF_RSS)
            events = []
            for entry in feed.entries:
                t = self._parse_time(entry)
                if not t: continue
                impact   = self._impact(entry)
                currency = getattr(entry, "country", "").upper()
                events.append({
                    "title":    entry.get("title",""),
                    "time_utc": t,
                    "impact":   impact,
                    "currency": currency,
                    "forecast": entry.get("forecast",""),
                    "previous": entry.get("previous",""),
                })
            self.events      = events
            self._refresh_ts = datetime.now(timezone.utc)
            os.makedirs("data", exist_ok=True)
            with open("data/news_events.json","w") as f:
                json.dump(self.events, f, default=str, indent=2)
            print(f"[News] ✓ {len(events)} eventos carregados")
        except Exception as e:
            print(f"[News] Erro: {e}")
            self._load_cache()

    def is_blocked(self, symbol: str = None) -> tuple[bool, Optional[dict]]:
        if not self.events: self.refresh()
        now = datetime.now(timezone.utc)
        for ev in self.events:
            if ev["impact"] != "HIGH": continue
            diff = (ev["time_utc"] - now).total_seconds() / 60
            if -self.BLOCK_AFTER <= diff <= self.BLOCK_BEFORE:
                if symbol:
                    affected = self.SYMBOL_CURRENCIES.get(symbol, [])
                    if ev["currency"] not in affected: continue
                return True, {
                    "event":    ev["title"],
                    "currency": ev["currency"],
                    "mins_to":  round(diff),
                    "time_utc": str(ev["time_utc"]),
                }
        return False, None

    def upcoming(self, hours: int = 24) -> list:
        if not self.events: self.refresh()
        now    = datetime.now(timezone.utc)
        cutoff = now + timedelta(hours=hours)
        result = []
        for ev in self.events:
            if ev["impact"] == "HIGH" and now < ev["time_utc"] < cutoff:
                h = (ev["time_utc"] - now).total_seconds() / 3600
                result.append({**ev, "hours_to": round(h, 1)})
        return sorted(result, key=lambda x: x["time_utc"])

    def next_event(self) -> Optional[dict]:
        u = self.upcoming(48)
        return u[0] if u else None

    def _parse_time(self, entry) -> Optional[datetime]:
        try:
            tt = entry.get("published_parsed")
            if tt: return datetime.fromtimestamp(time.mktime(tt), tz=timezone.utc)
        except: pass
        return None

    def _impact(self, entry) -> str:
        for tag in entry.get("tags", []):
            t = tag.term.lower()
            if "high"   in t: return "HIGH"
            if "medium" in t: return "MEDIUM"
        title = entry.get("title","").upper()
        if any(k.upper() in title for k in self.HIGH_IMPACT_KEYWORDS):
            return "HIGH"
        return "LOW"

    def _load_cache(self):
        try:
            with open("data/news_events.json") as f:
                self.events = json.load(f)
        except: self.events = []
