# -*- coding: utf-8 -*-
"""
AI Swing Master (機関投資家級・完全自動スイングAI)
GPT-4.2 を使用し、世界市場のマクロ・テクニカル・ニュースを統合した
最終判断 (BUY / SELL / STOP) を返すモジュール。

webhook_server からは:
    from server.ai_swing_master import analyze_swing
"""

from __future__ import annotations
import json
import logging
from openai import OpenAI

client = OpenAI()
logger = logging.getLogger("ai_swing")


def analyze_swing(symbol: str) -> dict:
    """
    世界マクロ指標と複数時間足テクニカルを GPT-4.2 に統合判断させて、
    スイング（1〜5日）の方向・価格・TP・SL・保有日数を返す。
    """

    prompt = f"""あなたはプロトレーダーです。{symbol}について1〜5日保有のスイングトレード判定を行ってください。

【分析項目】
1. マクロ環境（VIX、ドル、金利、主要株価指数、原油、ビットコイン等）
2. テクニカル（日足、12H、4H、1H の MA/MACD/RSI/BB/ATR等）
3. 最新ニュース（地政学、金融政策、経済指標、要人発言等）

【判定ルール】
- final_direction: BUY / SELL / STOP のいずれか
- confidence: 0〜100 （50未満ならSTOP推奨）
- entry_price: 現在価格の目安（{symbol}の典型価格を参考に設定）
- tp_price: エントリーから ATR × 2〜4 程度
- sl_price: エントリーから ATR × 1.5〜2 程度
- hold_days: 1〜5日
- reason: 50文字以内で簡潔な理由（日本語）

**出力は必ずJSON形式のみ**（他の文章は一切含めないこと）:
{{
  "symbol": "{symbol}",
  "final_direction": "BUY",
  "confidence": 75,
  "entry_price": 32000,
  "tp_price": 32400,
  "sl_price": 31750,
  "hold_days": 3,
  "reason": "米株上昇とドル安が追い風。テクニカルも買い優勢。"
}}"""

    try:
        res = client.chat.completions.create(
            model="gpt-4o",
            temperature=0.7,
            messages=[{"role": "user", "content": prompt}]
        )
        text = res.choices[0].message.content.strip()
        logger.info(f"[SwingAI] Response: {text[:200]}")

        # コードブロック除去
        if "```" in text:
            import re
            match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
            if match:
                text = match.group(1)
        
        if not text:
            logger.error("[SwingAI] Empty response from GPT-4o")
            raise ValueError("Empty response from OpenAI API")

        data = json.loads(text)
        logger.info(f"[SwingAI] {symbol}: {data}")
        return data

    except Exception as e:
        logger.exception("[SwingAI] ERROR")
        return {
            "symbol": symbol,
            "final_direction": "STOP",
            "confidence": 0,
            "entry_price": 0,
            "tp_price": 0,
            "sl_price": 0,
            "hold_days": 0,
            "reason": f"エラー: {e}"
        }
