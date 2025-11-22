#!/usr/bin/env python3
"""
自動ポジション追跡システム
notification_history.jsonから過去24時間のシグナルを抽出し、
current_positions.jsonを自動更新
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

# 設定
ROOT = Path(__file__).parent
NOTIFICATION_LOG = ROOT / "logs" / "notification_history.json"
POSITION_FILE = ROOT / "current_positions.json"
TRACKING_HOURS = 24  # 24時間以内のシグナルを追跡

# 銘柄名の正規化マッピング
SYMBOL_NORMALIZE = {
    'JP225': 'JP225',
    '日経225': 'JP225',
    '日本225': 'JP225',
    'DE40': 'DE40',
    'ドイツ40': 'DE40',
    'NASDAQ_MINI': 'NASDAQ_MINI',
    '米国NQ100ミニ': 'NASDAQ_MINI',
    'GOLD_SPOT': 'GOLD_SPOT',
    '金スポット': 'GOLD_SPOT',
    'SILVER_SPOT': 'SILVER_SPOT',
    '銀スポット': 'SILVER_SPOT',
    'NATURAL_GAS': 'NATURAL_GAS',
    '天然ガス': 'NATURAL_GAS'
}


def load_notification_history():
    """通知履歴を読み込み"""
    if not NOTIFICATION_LOG.exists():
        print(f"⚠️ 通知履歴が見つかりません: {NOTIFICATION_LOG}")
        return {}
    
    with open(NOTIFICATION_LOG, 'r', encoding='utf-8') as f:
        return json.load(f)


def extract_positions_from_history(history):
    """
    通知履歴から過去24時間のポジションを抽出
    
    notification_history.jsonの形式:
    {
        "STRONG_GO_DE40_24111.45_2025-11-03 22:30:00": "2025-11-04T13:15:00",
        ...
    }
    """
    cutoff_time = datetime.now() - timedelta(hours=TRACKING_HOURS)
    positions = []
    seen_symbols = {}  # 重複排除用（最新のみ保持）
    
    for key, timestamp_str in history.items():
        try:
            # タイムスタンプ解析
            notification_time = datetime.fromisoformat(timestamp_str)
            
            # 24時間以内かチェック
            if notification_time < cutoff_time:
                continue
            
            # キーをパース: "SIGNAL_SYMBOL_price_event_date_time"
            parts = key.split('_')
            if len(parts) < 3:
                continue
            
            signal_type = parts[0]  # 'STRONG' or 'GO'
            
            # 銘柄名を抽出（GOLD_SPOT, NASDAQ_MINIなど2単語の場合を考慮）
            if parts[1] in ['GOLD', 'SILVER', 'NATURAL', 'NASDAQ']:
                if parts[1] == 'NASDAQ' and len(parts) > 2 and parts[2] == 'MINI':
                    symbol_raw = 'NASDAQ_MINI'
                    price_idx = 3
                elif parts[1] == 'GOLD' and len(parts) > 2 and parts[2] == 'SPOT':
                    symbol_raw = 'GOLD_SPOT'
                    price_idx = 3
                elif parts[1] == 'SILVER' and len(parts) > 2 and parts[2] == 'SPOT':
                    symbol_raw = 'SILVER_SPOT'
                    price_idx = 3
                elif parts[1] == 'NATURAL' and len(parts) > 2 and parts[2] == 'GAS':
                    symbol_raw = 'NATURAL_GAS'
                    price_idx = 3
                else:
                    symbol_raw = parts[1]
                    price_idx = 2
            else:
                symbol_raw = parts[1]  # DE40, JP225
                price_idx = 2
            
            # 銘柄名を正規化
            symbol = SYMBOL_NORMALIZE.get(symbol_raw, symbol_raw)
            
            # GMO 6銘柄のみ対象
            if symbol not in ['JP225', 'NASDAQ_MINI', 'DE40', 'GOLD_SPOT', 'SILVER_SPOT', 'NATURAL_GAS']:
                continue
            
            # 価格を抽出
            try:
                price = float(parts[price_idx])
            except (ValueError, IndexError):
                price = 0.0
            
            # 方向を判定（CSVから取得する必要があるが、デフォルトはbuy）
            # 注: 今回は通知時の方向情報がないため、トレンド分析で再判定
            direction = 'buy'  # プレースホルダー
            
            # 同じ銘柄の古いエントリーを上書き（最新のみ）
            if symbol not in seen_symbols or notification_time > datetime.fromisoformat(seen_symbols[symbol]['entry_time']):
                position = {
                    'symbol': symbol,
                    'direction': direction,  # 反転監視で再判定される
                    'entry_time': notification_time.isoformat(),
                    'entry_price': price,
                    'lots': 6 if signal_type == 'STRONG' else 4,
                    'notification_key': key,
                    'note': f"自動追跡: {notification_time.strftime('%Y-%m-%d %H:%M')}に{signal_type}_GO通知"
                }
                seen_symbols[symbol] = position
            
        except Exception as e:
            print(f"⚠️ キー解析エラー: {key} - {e}")
            continue
    
    # 重複排除後のリストを返す
    return list(seen_symbols.values())


def merge_with_manual_positions(auto_positions):
    """
    自動抽出したポジションと手動登録ポジションをマージ
    手動登録が優先（ロット数調整など反映）
    """
    # 既存の手動ポジションを読み込み
    manual_positions = []
    if POSITION_FILE.exists():
        with open(POSITION_FILE, 'r', encoding='utf-8') as f:
            manual_positions = json.load(f)
    
    # 手動ポジションの銘柄リスト
    manual_symbols = {pos['symbol']: pos for pos in manual_positions}
    
    # 自動ポジションから、手動登録されていないものを追加
    merged = list(manual_positions)  # 手動が優先
    
    for auto_pos in auto_positions:
        symbol = auto_pos['symbol']
        if symbol not in manual_symbols:
            merged.append(auto_pos)
    
    return merged


def save_positions(positions):
    """ポジション情報を保存"""
    with open(POSITION_FILE, 'w', encoding='utf-8') as f:
        json.dump(positions, f, ensure_ascii=False, indent=2)


def main():
    """メイン処理"""
    print("=" * 60)
    print("🔄 自動ポジション追跡システム")
    print("=" * 60)
    
    # 1. 通知履歴を読み込み
    history = load_notification_history()
    print(f"📊 通知履歴: {len(history)}件")
    
    if not history:
        print("⚠️ 追跡可能なシグナルがありません")
        return
    
    # 2. 過去24時間のポジションを抽出
    auto_positions = extract_positions_from_history(history)
    print(f"✅ 自動抽出: {len(auto_positions)}件（過去{TRACKING_HOURS}時間）")
    
    if auto_positions:
        print("\n📈 抽出されたポジション:")
        for pos in auto_positions:
            direction_emoji = "🟢 買い" if pos['direction'] == 'buy' else "🔴 売り"
            print(f"  - {pos['symbol']}: {direction_emoji} {pos['entry_price']:,.2f} ({pos['lots']}ロット)")
    
    # 3. 手動ポジションとマージ
    merged_positions = merge_with_manual_positions(auto_positions)
    print(f"\n💾 最終ポジション: {len(merged_positions)}件")
    
    # 4. 保存
    save_positions(merged_positions)
    print(f"✅ 保存完了: {POSITION_FILE}")
    
    print("=" * 60)


if __name__ == '__main__':
    main()
