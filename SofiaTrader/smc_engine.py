import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timezone

@dataclass
class SMCAnalysis:
    symbol:       str
    timeframe:    str
    bias:         str            # BULLISH / BEARISH / NEUTRAL
    bos:          Optional[str]  # BOS_BULL / BOS_BEAR / None
    choch:        Optional[str]  # CHOCH_BULL / CHOCH_BEAR / None
    order_block:  Optional[dict] # {type, high, low, mid}
    fvg:          Optional[dict] # {type, high, low}
    liquidity:    Optional[dict] # {type, level}
    killzone:     str            # London / NY / Asia / None
    confidence:   float          # 0-100
    entry_zone:   Optional[tuple]
    sl_level:     Optional[float]
    tp_targets:   list
    setup_quality: str           # A+ / A / B / C
    summary:      str

class SofiaSmcEngine:

    KILLZONES = {"Asia": (0, 3), "London": (7, 10), "NY": (13, 16)}

    def analyse(self, df: pd.DataFrame, symbol: str, tf: str,
                utc_hour: int = None) -> SMCAnalysis:
        if df is None or len(df) < 50:
            return self._empty(symbol, tf)
        bias  = self._bias(df)
        bos   = self._bos(df)
        choch = self._choch(df)
        ob    = self._order_block(df, bias)
        fvg   = self._fvg(df, bias)
        liq   = self._liquidity(df, bias)
        kz    = self._killzone(utc_hour)
        conf  = self._confidence(bias, bos, choch, ob, fvg, liq, kz)
        entry = self._entry(ob, fvg)
        sl    = self._sl(ob, fvg, bias)
        tps   = self._tps(df, bias, entry, liq)
        qual  = self._quality(conf, bos, choch, ob, fvg, kz)
        summ  = self._summary(symbol, tf, bias, bos, choch, ob, fvg, liq, kz, conf)
        return SMCAnalysis(symbol=symbol, timeframe=tf, bias=bias,
            bos=bos, choch=choch, order_block=ob, fvg=fvg,
            liquidity=liq, killzone=kz, confidence=conf,
            entry_zone=entry, sl_level=sl, tp_targets=tps,
            setup_quality=qual, summary=summ)

    def _bias(self, df):
        highs, lows = df["h"].values[-20:], df["l"].values[-20:]
        hh = sum(highs[i] > highs[i-1] for i in range(1, len(highs)))
        hl = sum(lows[i]  > lows[i-1]  for i in range(1, len(lows)))
        lh = sum(highs[i] < highs[i-1] for i in range(1, len(highs)))
        ll = sum(lows[i]  < lows[i-1]  for i in range(1, len(lows)))
        if hh + hl > (lh + ll) * 1.3: return "BULLISH"
        if lh + ll > (hh + hl) * 1.3: return "BEARISH"
        return "NEUTRAL"

    def _bos(self, df):
        if len(df) < 20: return None
        last, prev = df.iloc[-1], df.iloc[-21:-1]
        if last["c"] > prev["h"].max(): return "BOS_BULL"
        if last["c"] < prev["l"].min(): return "BOS_BEAR"
        return None

    def _choch(self, df):
        if len(df) < 30: return None
        r, p = df.iloc[-15:], df.iloc[-30:-15]
        if r["l"].min() > p["l"].min() and r["c"].iloc[-1] > r["o"].iloc[-1]: return "CHOCH_BULL"
        if r["h"].max() < p["h"].max() and r["c"].iloc[-1] < r["o"].iloc[-1]: return "CHOCH_BEAR"
        return None

    def _order_block(self, df, bias):
        for i in range(len(df)-3, max(0, len(df)-30), -1):
            c, n = df.iloc[i], df.iloc[i+1] if i+1 < len(df) else None
            if n is None: continue
            body = abs(c["c"] - c["o"])
            span = c["h"] - c["l"]
            if span == 0: continue
            if bias == "BULLISH" and c["c"] < c["o"] and body/span > 0.5 and n["c"] > c["h"]:
                return {"type":"BULLISH","high":round(c["h"],5),"low":round(c["l"],5),"mid":round((c["h"]+c["l"])/2,5)}
            if bias == "BEARISH" and c["c"] > c["o"] and body/span > 0.5 and n["c"] < c["l"]:
                return {"type":"BEARISH","high":round(c["h"],5),"low":round(c["l"],5),"mid":round((c["h"]+c["l"])/2,5)}
        return None

    def _fvg(self, df, bias):
        current_price = df["c"].iloc[-1]
        for i in range(len(df)-4, max(0, len(df)-25), -1):
            c1, c3 = df.iloc[i], df.iloc[i+2]
            if bias == "BULLISH" and c3["l"] > c1["h"]:
                gap_low, gap_high = round(c1["h"],5), round(c3["l"],5)
                mitigated = current_price <= gap_high
                return {"type":"BULLISH","high":gap_high,"low":gap_low,"mitigated":mitigated}
            if bias == "BEARISH" and c3["h"] < c1["l"]:
                gap_low, gap_high = round(c3["h"],5), round(c1["l"],5)
                mitigated = current_price >= gap_low
                return {"type":"BEARISH","high":gap_high,"low":gap_low,"mitigated":mitigated}
        return None

    def _liquidity(self, df, bias):
        """Identifica a piscina de liquidez (BSL/SSL) da janela recente e
        assinala se já foi varrida: a última vela fez wick para além do
        máximo/mínimo anterior mas fechou de novo dentro do range — o
        padrão clássico ICT de liquidity sweep antes da reversão."""
        if bias == "NEUTRAL":
            return None
        window = df.iloc[-20:]
        last   = df.iloc[-1]
        prior  = df.iloc[-20:-1]
        if bias == "BULLISH":
            level = round(window["h"].max(), 5)
            swept = bool(last["h"] > prior["h"].max() and last["c"] < prior["h"].max())
            return {"type": "BSL", "level": level, "swept": swept}
        level = round(window["l"].min(), 5)
        swept = bool(last["l"] < prior["l"].min() and last["c"] > prior["l"].min())
        return {"type": "SSL", "level": level, "swept": swept}

    def _killzone(self, utc_hour=None):
        h = utc_hour or datetime.now(timezone.utc).hour
        for kz, (s, e) in self.KILLZONES.items():
            if s <= h < e: return kz
        return "None"

    def _confidence(self, bias, bos, choch, ob, fvg, liq, kz):
        s = 0
        if bias != "NEUTRAL": s += 20
        if bos:   s += 20
        if choch: s += 15
        if ob:    s += 20
        if fvg and not fvg.get("mitigated"): s += 10
        if liq:
            s += 10
            if liq.get("swept"): s += 5  # sweep recente = confluência extra de reversão
        if kz != "None": s += 5
        return min(s, 100.0)

    def _entry(self, ob, fvg):
        if ob:  return (ob["low"], ob["high"])
        if fvg: return (fvg["low"], fvg["high"])
        return None

    def _sl(self, ob, fvg, bias):
        if ob:  return ob["low"]*0.9995  if bias == "BULLISH" else ob["high"]*1.0005
        if fvg: return fvg["low"]*0.9995 if bias == "BULLISH" else fvg["high"]*1.0005
        return None

    def _tps(self, df, bias, entry, liq):
        if not entry: return []
        base = (entry[0]+entry[1])/2
        atr  = (df["h"]-df["l"]).rolling(14).mean().iloc[-1]
        mult = [1.5, 3.0, 5.0]
        if bias == "BULLISH":
            tps = [round(base+atr*m,5) for m in mult]
        else:
            tps = [round(base-atr*m,5) for m in mult]
        if liq: tps.append(liq["level"])
        return tps

    def _quality(self, conf, bos, choch, ob, fvg, kz):
        if conf >= 80 and bos and ob and kz != "None": return "A+"
        if conf >= 65 and (bos or choch) and ob:       return "A"
        if conf >= 50:                                  return "B"
        return "C"

    def _summary(self, symbol, tf, bias, bos, choch, ob, fvg, liq, kz, conf):
        lines = [f"[{symbol} {tf}] Bias: {bias} | Conf: {conf:.0f}%"]
        if bos:   lines.append(f"  BOS: {bos}")
        if choch: lines.append(f"  CHoCH: {choch}")
        if ob:    lines.append(f"  OB {ob['type']}: {ob['low']}-{ob['high']}")
        if fvg:   lines.append(f"  FVG {fvg['type']}: {fvg['low']}-{fvg['high']}" + (" (mitigado)" if fvg.get("mitigated") else ""))
        if liq:   lines.append(f"  Liq {liq['type']}: {liq['level']}" + (" (varrida)" if liq.get("swept") else ""))
        if kz != "None": lines.append(f"  Killzone: {kz}")
        return "\n".join(lines)

    def _empty(self, symbol, tf):
        return SMCAnalysis(symbol=symbol, timeframe=tf, bias="NEUTRAL",
            bos=None, choch=None, order_block=None, fvg=None, liquidity=None,
            killzone="None", confidence=0, entry_zone=None, sl_level=None,
            tp_targets=[], setup_quality="C", summary="Dados insuficientes")


def mtf_analyse(bridge, symbol: str) -> dict:
    """Análise multi-timeframe H4/H1/M15 com score de confluência"""
    engine = SofiaSmcEngine()
    results = {tf: engine.analyse(bridge.get_ohlcv(symbol, tf, 200), symbol, tf)
               for tf in ["H4","H1","M15"]}
    biases = [r.bias for r in results.values()]
    bull, bear = biases.count("BULLISH"), biases.count("BEARISH")
    confluence = ("STRONG_BULL" if bull==3 else "BULL" if bull>=2 else
                  "STRONG_BEAR" if bear==3 else "BEAR" if bear>=2 else "MIXED")
    return {"timeframes": results, "confluence": confluence}
