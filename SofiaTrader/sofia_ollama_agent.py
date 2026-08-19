import ollama
import json
from dataclasses import dataclass
from typing import Optional

@dataclass
class TradeDecision:
    action:     str    # BUY / SELL / WAIT
    confidence: float
    lot_size:   float
    entry:      float
    sl:         float
    tp1:        float
    tp2:        float
    tp3:        float
    reasoning:  str
    risk_reward: float
    news_risk:  str    # LOW / MEDIUM / HIGH

class SofiaOllamaAgent:

    MODEL = "deepseek-r1:7b"

    SYSTEM = """És a Sofia, trader profissional SMC/ICT com 10 anos de experiência.
Especialista em XAUUSD e BTCUSD. Analisas Order Blocks, FVG, BOS, CHoCH, Liquidity, Killzones.
Regras de risco: máximo 1-2% por trade. Só entras em setups A ou A+.
Responde SEMPRE em JSON válido sem texto adicional."""

    def decide_trade(self, analysis, account_balance: float,
                     news_upcoming: bool = False, spread: float = 0) -> TradeDecision:
        prompt = f"""
Analisa e decide:

SÍMBOLO: {analysis.symbol} | TF: {analysis.timeframe}
BIAS: {analysis.bias} | BOS: {analysis.bos} | CHOCH: {analysis.choch}
ORDER BLOCK: {analysis.order_block}
FVG: {analysis.fvg}
LIQUIDEZ: {analysis.liquidity}
KILLZONE: {analysis.killzone}
CONFIANÇA: {analysis.confidence}% | QUALIDADE: {analysis.setup_quality}
ENTRADA: {analysis.entry_zone} | SL: {analysis.sl_level} | TPS: {analysis.tp_targets}

CONTA: ${account_balance:.2f} | SPREAD: {spread} pips
NOTÍCIAS: {"⚠️ SIM - REDUZIR RISCO" if news_upcoming else "Não"}

Responde APENAS com JSON:
{{
  "action": "BUY|SELL|WAIT",
  "confidence": 0-100,
  "lot_size": 0.01,
  "entry": 0.0,
  "sl": 0.0,
  "tp1": 0.0,
  "tp2": 0.0,
  "tp3": 0.0,
  "reasoning": "breve explicação",
  "risk_reward": 0.0,
  "news_risk": "LOW|MEDIUM|HIGH"
}}"""
        try:
            resp = ollama.chat(
                model=self.MODEL,
                messages=[{"role":"system","content":self.SYSTEM},
                          {"role":"user","content":prompt}],
                options={"temperature":0.1,"num_predict":500}
            )
            content = resp["message"]["content"]
            # Limpar deepseek <think> tags
            if "</think>" in content:
                content = content.split("</think>")[-1]
            # Limpar markdown
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            return TradeDecision(**json.loads(content.strip()))
        except Exception as e:
            return TradeDecision(action="WAIT", confidence=0, lot_size=0,
                entry=0, sl=0, tp1=0, tp2=0, tp3=0,
                reasoning=f"Erro: {e}", risk_reward=0, news_risk="HIGH")

    def chat(self, message: str, context: str = "") -> str:
        """Chat livre sobre mercado em português"""
        resp = ollama.chat(
            model=self.MODEL,
            messages=[{"role":"system","content":self.SYSTEM},
                      {"role":"user","content":f"{context}\n\n{message}" if context else message}],
            options={"temperature":0.4,"num_predict":400}
        )
        content = resp["message"]["content"]
        if "</think>" in content:
            content = content.split("</think>")[-1].strip()
        return content

    def risk_check(self, positions: list, account: dict) -> str:
        pnl = sum(p["profit"] for p in positions)
        bal = account.get("balance", 0)
        dd  = abs(pnl)/bal*100 if pnl < 0 else 0
        return self.chat(
            f"Avalia risco: {len(positions)} posições, P&L ${pnl:.2f}, DD {dd:.1f}%. "
            f"Devo fechar alguma, ajustar SL ou manter? Máx 80 palavras.")
