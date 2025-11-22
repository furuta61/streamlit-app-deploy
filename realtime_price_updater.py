#!/usr/bin/env python3
"""
リアルタイム価格更新システム
CSVファイルの古い価格を最新の市場価格に自動更新
"""

import os
import yfinance as yf
import pandas as pd
from pathlib import Path
from datetime import datetime
import sys

# Yahoo Finance シンボルマッピング
SYMBOL_MAP = {
    # Use ETF as primary source for JP225 (more stable for programmatic fetch)
    'JP225': '1321.T',
    'DE40': '^GDAXI',
    'NASDAQ_MINI': 'NQ=F',
    'SP500': '^GSPC',
    'GOLD_SPOT': 'GC=F',
    'SILVER_SPOT': 'SI=F',
    'NATURAL_GAS': 'NG=F',
    'MSFT': 'MSFT',
    'AAPL': 'AAPL'
}

def get_realtime_price(symbol: str) -> float:
    """リアルタイム価格を取得"""
    try:
        # 高精度モード: アンサンブル取得器を優先（環境変数で有効化）
        if os.getenv('USE_HIGH_ACCURACY', '0') == '1' and symbol == 'JP225':
            try:
                from market_data_ensemble import get_price as ensemble_get_price
                res = ensemble_get_price('JP225')
                if res and res.get('price') is not None:
                    print(f"✅ {symbol} (ensemble): {res['price']:.2f} (conf={res.get('confidence'):.2f})")
                    return float(res['price'])
            except Exception as e:
                print(f"⚠️  ensemble fetch failed: {e}")

        yf_symbol = SYMBOL_MAP.get(symbol)
        if not yf_symbol:
            print(f"⚠️  未対応銘柄: {symbol}")
            return None

        ticker = yf.Ticker(yf_symbol)
        hist = ticker.history(period="1d", interval="1m")

        if hist.empty:
            print(f"⚠️  {symbol}: データ取得失敗")
            return None

        latest_price = hist['Close'].iloc[-1]
        print(f"✅ {symbol}: {latest_price:.2f}")
        return latest_price
    
    except Exception as e:
        print(f"❌ {symbol}: エラー - {e}")
        return None

def update_csv_prices(csv_path: Path) -> bool:
    """CSVファイルの価格を最新に更新"""
    try:
        # CSVファイル読み込み
        df = pd.read_csv(csv_path)
        print(f"\n📂 読込: {csv_path.name}")
        print(f"📊 行数: {len(df)}")

        # 空のCSVは非致命的に扱う（更新対象なし）
        if df.empty:
            print("⚠️  CSVは空です（行数0）。価格更新はスキップします。")
            return True

        # entry_source 列がない場合は非致命的にスキップ
        if 'entry_source' not in df.columns:
            print("⚠️  entry_source列がありません。価格更新はスキップします。")
            return True

        # entry列がない場合もスキップ
        if 'entry' not in df.columns:
            print("⚠️  entry列がありません。価格更新はスキップします。")
            return True
        
        # 各銘柄の価格を更新
        updated_count = 0
        for symbol in df['entry_source'].unique():
            if symbol not in SYMBOL_MAP:
                continue
            
            # リアルタイム価格取得
            new_price = get_realtime_price(symbol)
            if new_price is None:
                continue
            
            # 該当行の価格を更新
            mask = df['entry_source'] == symbol
            old_price = df.loc[mask, 'entry'].iloc[0]
            price_diff = new_price - old_price
            price_change_pct = (price_diff / old_price) * 100
            
            print(f"   旧価格: {old_price:.2f} → 新価格: {new_price:.2f} ({price_change_pct:+.2f}%)")
            
            # entry価格を更新
            df.loc[mask, 'entry'] = new_price
            
            # TP/SLも比例して更新（オプション）
            if 'TP' in df.columns and 'SL' in df.columns:
                tp_offset = df.loc[mask, 'TP'].iloc[0] - old_price
                sl_offset = df.loc[mask, 'SL'].iloc[0] - old_price
                df.loc[mask, 'TP'] = new_price + tp_offset
                df.loc[mask, 'SL'] = new_price + sl_offset
            
            updated_count += 1
        
        # 更新されたCSVを保存
        if updated_count > 0:
            # バックアップ作成
            backup_path = csv_path.parent / f"{csv_path.stem}_backup{csv_path.suffix}"
            df_original = pd.read_csv(csv_path)
            df_original.to_csv(backup_path, index=False)
            
            # 新しいCSVを保存
            df.to_csv(csv_path, index=False)
            print(f"\n✅ {updated_count}銘柄の価格を更新しました")
            print(f"💾 バックアップ: {backup_path.name}")
            return True
        else:
            print("\n⚠️  更新対象の銘柄がありませんでした（該当シンボルがSYMBOL_MAPにありません、または価格取得失敗）。")
            # 非致命的 - 成功として扱う（監視ループが停止しないようにする）
            return True
    
    except Exception as e:
        print(f"❌ エラー: {e}")
        import traceback
        traceback.print_exc()
        return False

def find_latest_csv() -> Path:
    """最新のCSVファイルを検索"""
    google_drive = Path.home() / "Google ドライブ" / "CFD3Pro"
    csv_files = list(google_drive.glob("events_scored_*.csv"))
    
    if not csv_files:
        raise FileNotFoundError("CSVファイルが見つかりません")
    
    # 最新のファイルを取得
    latest_csv = max(csv_files, key=lambda p: p.stat().st_mtime)
    return latest_csv

if __name__ == "__main__":
    print("🔄 リアルタイム価格更新システム")
    print("=" * 50)
    
    # 引数でCSVファイルを指定できる
    if len(sys.argv) > 1:
        csv_path = Path(sys.argv[1])
    else:
        csv_path = find_latest_csv()
    
    print(f"📁 対象ファイル: {csv_path.name}")
    print(f"⏰ 生成時刻: {datetime.fromtimestamp(csv_path.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # 価格更新実行
    success = update_csv_prices(csv_path)
    
    if success:
        print("\n🎉 価格更新が完了しました！")
        print(f"📂 更新後ファイル: {csv_path}")
    else:
        print("\n❌ 価格更新に失敗しました")
        sys.exit(1)
