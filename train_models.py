import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report
from lightgbm import LGBMClassifier
import joblib


# ======================
# データ読み込み
# ======================
def load_dataset(path="training_dataset.csv"):
    df = pd.read_csv(path)

    # 数値変換（念のため）
    numeric_cols = ["RSI", "SMA25", "SMA75", "MACD", "Signal",
                    "sentiment_pos", "sentiment_neg"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=numeric_cols)

    print(f"[INFO] Loaded {len(df)} rows from {path}")
    return df


# ======================
# モデル①：方向性予測モデル
# ======================
def build_direction_labels(df):
    """
    上昇 or 下降 を予測するためのラベル
    +1 なら TP1 or TP2 が entry より上でヒット
    -1 なら SL の方が先にヒット
    """
    df = df.copy()

    df["label_direction"] = df["result"].map({
        "+2": 1,
        "+1": 1,
        "-1": 0,
        "0": 0
    })

    return df


def train_direction_model(df):
    df = build_direction_labels(df)

    features = ["RSI", "SMA25", "SMA75", "MACD", "Signal",
                "sentiment_pos", "sentiment_neg"]

    X = df[features]
    y = df["label_direction"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, shuffle=True
    )

    model = LGBMClassifier()
    model.fit(X_train, y_train)

    pred = model.predict(X_test)
    acc = accuracy_score(y_test, pred)

    print("\n=== 方向性モデル（上昇/下降） ===")
    print(f"Accuracy: {acc:.3f}")
    print(classification_report(y_test, pred))

    joblib.dump(model, "direction_model.pkl")
    print("[INFO] Saved → direction_model.pkl")


# ======================
# モデル②：TP/SL 先到達モデル
# ======================
def build_tp_sl_labels(df):
    df = df.copy()

    df["label_tp_sl"] = df["hit_type"].map({
        "TP1": 1,
        "TP2": 2,
        "SL": -1,
        "NONE": 0
    })

    return df


def train_tp_sl_model(df):
    df = build_tp_sl_labels(df)

    features = ["RSI", "SMA25", "SMA75", "MACD", "Signal",
                "sentiment_pos", "sentiment_neg"]

    X = df[features]
    y = df["label_tp_sl"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, shuffle=True
    )

    model = LGBMClassifier()
    model.fit(X_train, y_train)

    pred = model.predict(X_test)
    acc = accuracy_score(y_test, pred)

    print("\n=== TP/SL 先到達モデル ===")
    print(f"Accuracy: {acc:.3f}")
    print(classification_report(y_test, pred))

    joblib.dump(model, "tp_sl_model.pkl")
    print("[INFO] Saved → tp_sl_model.pkl")


# ======================
# メイン
# ======================
if __name__ == "__main__":
    df = load_dataset()

    train_direction_model(df)
    train_tp_sl_model(df)

    print("\n=== 2つのモデルの学習が完了しました ===")
