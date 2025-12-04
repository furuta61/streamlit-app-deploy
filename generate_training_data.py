import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

# 対象銘柄と Yahoo シンボル
SYMBOL_MAP = {
    "日本225": "^N225",
    "米国NQ100ミニ": "^NDX",
    "ドイツ40": "^GDAXI",
    "金スポット": "GC=F"
}

# Dawn結果の例：
# [{'symbol': '日本225', 'entry': 49483, 'SL': ..., ...}, ...]
def load_dawn_results(path="dawn_results.csv"):
    """過去に出力した Dawn形式の解析結果を読み込む"""
    return pd.read_csv(path)


def fetch_4h_candles(yf_symbol, period="2y"):
    """Yahoo Finance から 1h足 → 4h足へ変換"""
    df = yf.download(yf_symbol, interval="60m", period=period)
    if df.empty:
        return None

    # MultiIndex列を平坦化
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    # 列名を小文字に統一
    df.columns = [c.lower() for c in df.columns]

    # 4h足にリサンプリング
    df_4h = df.resample("4h").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum"
    }).dropna()

    return df_4h


def judge_trade_result(candles, entry, sl, tp1, tp2, direction, entry_time):
    """
    entry_time 以降のローソク足で TP1/TP2/SL のどれが先にヒットしたか判定。
    direction: buy/sell
    """

    # entry_time をタイムゾーン対応（candlesのindexに合わせる）
    if candles.index.tz is not None:
        entry_time = pd.to_datetime(entry_time).tz_localize('UTC')
    else:
        entry_time = pd.to_datetime(entry_time).tz_localize(None)

    # entry_time より後のローソク足だけ使う
    trade_candles = candles[candles.index >= entry_time]

    for ts, row in trade_candles.iterrows():
        high = row["high"]
        low = row["low"]

        if direction == "buy":
            if high >= tp2:
                return "+2", "TP2", ts
            if high >= tp1:
                return "+1", "TP1", ts
            if low <= sl:
                return "-1", "SL", ts

        else:  # SELL方向（必要なら追加）
            if low <= tp2:
                return "+2", "TP2", ts
            if low <= tp1:
                return "+1", "TP1", ts
            if high >= sl:
                return "-1", "SL", ts

    # 期間内に触れない場合
    return "0", "NONE", None



def generate_training_dataset(dawn_csv="dawn_results.csv", output_csv="training_dataset.csv"):
    """ Dawn形式CSV → 勝敗学習用CSV を作成 """

    dawn = load_dawn_results(dawn_csv)
    records = []

    for _, row in dawn.iterrows():

        symbol = row.get("銘柄", row.get("symbol"))
        if not symbol or pd.isna(symbol):
            continue
        yf_symbol = SYMBOL_MAP.get(symbol)
        if not yf_symbol:
            continue
        
        direction = row.get("方向", "stay")
        if pd.isna(direction) or direction == "stay":
            continue
            
        # entry/sl/tp の取得（複数列名対応）
        entry = row.get("entry_price", row.get("entry", None))
        sl = row.get("SL", row.get("sl", None))
        tp1 = row.get("TP1", row.get("tp1", None))
        tp2 = row.get("TP2", row.get("tp2", None))
        
        # NaN/None チェック
        if any(pd.isna(v) or v is None for v in [entry, sl, tp1, tp2]):
            continue
            
        entry = float(entry)
        sl = float(sl)
        tp1 = float(tp1)
        tp2 = float(tp2)
        entry_time = pd.to_datetime(row["entry_time"])

        print(f"Fetching data for {symbol}...")

        candles = fetch_4h_candles(yf_symbol)
        if candles is None:
            print(f"Error: {symbol} のデータ取得失敗")
            continue

        result, hit_type, hit_time = judge_trade_result(
            candles=candles,
            entry=entry,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            direction=direction,
            entry_time=entry_time
        )

        record = {
            "symbol": symbol,
            "direction": direction,
            "entry": entry,
            "SL": sl,
            "TP1": tp1,
            "TP2": tp2,
            "result": result,
            "hit_type": hit_type,
            "hit_time": hit_time,
            "RSI": row["RSI"],
            "SMA25": row["SMA25"],
            "SMA75": row["SMA75"],
            "MACD": row["MACD"],
            "Signal": row["Signal"],
            "sentiment_pos": row["sentiment_pos"],
            "sentiment_neg": row["sentiment_neg"],
            "entry_time": entry_time
        }

        records.append(record)

    df = pd.DataFrame(records)
    df.to_csv(output_csv, index=False)
    print(f"\n🎉 学習用データ作成完了 → {output_csv}")


# 実行例
if __name__ == "__main__":
    generate_training_dataset()
