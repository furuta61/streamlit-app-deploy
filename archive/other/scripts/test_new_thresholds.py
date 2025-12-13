#!/usr/bin/env python3
import sys, os
ROOT = os.path.abspath(".")
sys.path.insert(0, ROOT)

os.environ["TECH_WEIGHT"] = "1.0"
os.environ["NEWS_WEIGHT"] = "0.0"
os.environ["GO_THRESHOLD"] = "4.5"
os.environ["STRONG_GO_THRESHOLD"] = "5.5"

import importlib, mygpt_strategy as M
importlib.reload(M)

print("=== 新設定確認 ===")
print(f"TECH_WEIGHT: {M.TECH_WEIGHT}")
print(f"NEWS_WEIGHT: {M.NEWS_WEIGHT}")
print(f"GO_THRESHOLD: {M.GO_THRESHOLD}")
print(f"STRONG_GO_THRESHOLD: {M.STRONG_GO_THRESHOLD}")

print("\n=== STRONG_GO (勝率90%の高信頼シグナル) ===")
payload = {"symbol": "JP225", "price": 51200, "signal": "STRONG_GO", "news_items": [], "sentiment_score": 0.0}
result = M.analyze_signal("JP225", payload)
print(f"  tech_score: {result.get('tech_score')}")
print(f"  rating: {result.get('rating')}")
print(f"  decision: {result.get('decision')}")

print("\n=== GO (勝率90%シグナル) ===")
payload["signal"] = "GO"
result = M.analyze_signal("JP225", payload)
print(f"  tech_score: {result.get('tech_score')}")
print(f"  rating: {result.get('rating')}")
print(f"  decision: {result.get('decision')}")

print("\n=== WAIT (様子見) ===")
payload["signal"] = "WAIT"
result = M.analyze_signal("JP225", payload)
print(f"  tech_score: {result.get('tech_score')}")
print(f"  rating: {result.get('rating')}")
print(f"  decision: {result.get('decision')}")
