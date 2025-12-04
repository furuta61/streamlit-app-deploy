#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ダミーAIモデル作成（学習データ不足時の暫定モデル）
"""
import joblib
from lightgbm import LGBMClassifier
import numpy as np
import pandas as pd

# ダミーデータ作成
np.random.seed(42)
X_dummy = pd.DataFrame({
    "RSI": np.random.uniform(30, 70, 100),
    "SMA25": np.random.uniform(20000, 30000, 100),
    "SMA75": np.random.uniform(20000, 30000, 100),
    "MACD": np.random.uniform(-50, 50, 100),
    "Signal": np.random.uniform(-50, 50, 100),
    "sentiment_pos": np.random.uniform(20, 70, 100),
    "sentiment_neg": np.random.uniform(10, 40, 100)
})

# 方向性モデル（上昇/下降）
y_direction = np.random.choice([0, 1], 100, p=[0.4, 0.6])
direction_model = LGBMClassifier(n_estimators=10, max_depth=3, random_state=42, verbose=-1)
direction_model.fit(X_dummy, y_direction)
joblib.dump(direction_model, "direction_model.pkl")
print("✓ direction_model.pkl created (dummy)")

# TP/SL到達モデル
y_tp_sl = np.random.choice([-1, 0, 1, 2], 100, p=[0.2, 0.3, 0.3, 0.2])
tp_sl_model = LGBMClassifier(n_estimators=10, max_depth=3, random_state=42, verbose=-1)
tp_sl_model.fit(X_dummy, y_tp_sl)
joblib.dump(tp_sl_model, "tp_sl_model.pkl")
print("✓ tp_sl_model.pkl created (dummy)")

print("\n🎉 ダミーモデル作成完了")
print("→ サーバを再起動すると AI_Score が実値（0.4-0.7程度）になります")
