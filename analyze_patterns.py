import pandas as pd
import numpy as np

# =========
# 勝ちパターン分析AI
# =========

def load_dataset(path="training_dataset.csv"):
    df = pd.read_csv(path)
    print(f"[INFO] Loaded {len(df)} trades from {path}")
    return df


def winrate(series):
    """+1/+2 を勝ち、-1 を負けとして勝率を返す"""
    if len(series) == 0:
        return 0
    wins = ((series == "+1") | (series == "+2")).sum()
    return wins / len(series)


def analyze_rsi(df):
    print("\n=== RSI 勝率分析 ===")
    bins = list(range(0, 110, 10))
    df["RSI_bin"] = pd.cut(df["RSI"], bins=bins)

    table = df.groupby("RSI_bin")["result"].apply(winrate)
    print(table)
    return table


def analyze_trend(df):
    print("\n=== トレンド（SMA25 vs SMA75）勝率 ===")
    df["trend"] = np.where(df["SMA25"] > df["SMA75"], "UP",
                           np.where(df["SMA25"] < df["SMA75"], "DOWN", "FLAT"))

    table = df.groupby("trend")["result"].apply(winrate)
    print(table)
    return table


def analyze_momentum(df):
    print("\n=== モメンタム（MACD vs Signal）勝率 ===")
    df["momentum"] = np.where(df["MACD"] > df["Signal"], "UP", "DOWN")
    table = df.groupby("momentum")["result"].apply(winrate)
    print(table)
    return table


def analyze_sentiment(df):
    print("\n=== ニュース感情勝率（pos > neg ?） ===")
    df["sentiment_bias"] = np.where(df["sentiment_pos"] > df["sentiment_neg"],
                                    "Positive",
                                    np.where(df["sentiment_pos"] < df["sentiment_neg"],
                                             "Negative", "Neutral"))
    table = df.groupby("sentiment_bias")["result"].apply(winrate)
    print(table)
    return table


def analyze_tp_sl(df):
    print("\n=== TP/SL 到達率分析 ===")
    total = len(df)

    tp1 = (df["hit_type"] == "TP1").sum()
    tp2 = (df["hit_type"] == "TP2").sum()
    sl = (df["hit_type"] == "SL").sum()

    print(f"TP1到達率 : {tp1/total:.2f}")
    print(f"TP2到達率 : {tp2/total:.2f}")
    print(f"SL到達率  : {sl/total:.2f}")

    return {
        "TP1": tp1/total,
        "TP2": tp2/total,
        "SL": sl/total
    }


def analyze_symbol(df):
    print("\n=== 銘柄別勝率 ===")
    table = df.groupby("symbol")["result"].apply(winrate)
    print(table)
    return table


def analyze_direction(df):
    print("\n=== 方向（direction）別勝率 ===")
    table = df.groupby("direction")["result"].apply(winrate)
    print(table)
    return table


def analyze_entry_time(df):
    print("\n=== 時間帯（entry_time）勝率 ===")
    df["hour"] = pd.to_datetime(df["entry_time"]).dt.hour
    table = df.groupby("hour")["result"].apply(winrate)
    print(table)
    return table


def main():
    df = load_dataset()

    analyze_rsi(df)
    analyze_trend(df)
    analyze_momentum(df)
    analyze_sentiment(df)
    analyze_tp_sl(df)
    analyze_symbol(df)
    analyze_direction(df)
    analyze_entry_time(df)

    print("\n=== すべての分析が完了しました ===")

if __name__ == "__main__":
    main()
