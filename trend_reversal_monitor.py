#!/usr/bin/env python3
"""
トレンド反転監視システム
既存ポジションに対するトレンド反転を検知し、即座にGmail通知
"""

import json
import os
import yagmail
from datetime import datetime, timedelta
from pathlib import Path
from trend_analyzer import calculate_trend_signals

# 設定
POSITION_FILE = Path(__file__).parent / "current_positions.json"
HISTORY_FILE = Path(__file__).parent / "logs/reversal_history.json"
GMAIL_FROM = "furuta61@gmail.com"
GMAIL_TO = "furuta61@gmail.com"

# 監視対象銘柄のマッピング
SYMBOL_MAP = {
    'DE40': 'ドイツ40',
    'GOLD_SPOT': '金スポット',
    'NASDAQ_MINI': '米国NQ100ミニ',
    'JP225': '日経225',
    'SILVER_SPOT': '銀スポット',
    'NATURAL_GAS': '天然ガス'
}

# --- 反転アラートの動作モード ---
# REVERSAL_ALERT_MODE: 'default' (既存の閾値) or 'urgent_only' (より厳しい条件でのみ通知)
REVERSAL_ALERT_MODE = os.environ.get('REVERSAL_ALERT_MODE', 'default')
# 通常モードの強度閾値（既存ロジック）
REVERSAL_STRENGTH_THRESHOLD = float(os.environ.get('REVERSAL_STRENGTH_THRESHOLD', '0.7'))
# 緊急モードで必要とする強度（例: 0.85 以上）
REVERSAL_URGENT_STRENGTH = float(os.environ.get('REVERSAL_URGENT_STRENGTH', '0.85'))
# 緊急通知のための未実現損失閾値（%、例: 1.0 -> 1%）
REVERSAL_LOSS_PCT_THRESHOLD = float(os.environ.get('REVERSAL_LOSS_PCT_THRESHOLD', '1.0'))


def load_positions():
    """現在のポジション情報を読み込む"""
    if not POSITION_FILE.exists():
        return []
    
    with open(POSITION_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_positions(positions):
    """ポジション情報を保存"""
    with open(POSITION_FILE, 'w', encoding='utf-8') as f:
        json.dump(positions, f, ensure_ascii=False, indent=2)


def check_reversal(position):
    """
    ポジションに対してトレンド反転を検知
    
    Returns:
        dict: 反転情報 or None
    """
    symbol = position['symbol']
    direction = position['direction']  # 'buy' or 'sell'
    entry_time = datetime.fromisoformat(position['entry_time'])
    entry_price = position['entry_price']
    
    # トレンド分析実行
    print(f"[CHECK] {symbol} のトレンド確認中...")
    trend = calculate_trend_signals(symbol, period='30d', interval='1h')

    if trend['direction'] == 'NEUTRAL':
        return None

    # 反転検知
    is_reversed = False
    if direction == 'buy' and trend['direction'] == 'SELL':
        is_reversed = True
        reversal_type = '買い → 売り'
    elif direction == 'sell' and trend['direction'] == 'BUY':
        is_reversed = True
        reversal_type = '売り → 買い'

    if not is_reversed:
        return None

    strength = float(trend.get('strength', 0.0))

    # 現在価格を取り、未実現損失率を計算（方向に依存）
    current_price = float(trend.get('current_price', entry_price))
    if direction == 'buy':
        unrealized_pct = (entry_price - current_price) / entry_price * 100.0
    else:
        unrealized_pct = (current_price - entry_price) / entry_price * 100.0

    # モードに応じた閾値判定
    if REVERSAL_ALERT_MODE == 'urgent_only':
        # 強度と未実現損失が両方閾値を超える場合のみ通知
        if strength >= REVERSAL_URGENT_STRENGTH and unrealized_pct >= REVERSAL_LOSS_PCT_THRESHOLD:
            return {
                'symbol': symbol,
                'symbol_jp': SYMBOL_MAP.get(symbol, symbol),
                'reversal_type': reversal_type,
                'old_direction': direction,
                'new_direction': trend['direction'].lower(),
                'strength': strength,
                'entry_time': entry_time.strftime('%Y-%m-%d %H:%M'),
                'entry_price': entry_price,
                'current_price': current_price,
                'unrealized_pct': unrealized_pct,
                'detected_at': datetime.now().isoformat()
            }
        else:
            return None
    else:
        # default 動作: 既存の強度閾値で通知
        threshold = REVERSAL_STRENGTH_THRESHOLD
        if strength >= threshold:
            return {
                'symbol': symbol,
                'symbol_jp': SYMBOL_MAP.get(symbol, symbol),
                'reversal_type': reversal_type,
                'old_direction': direction,
                'new_direction': trend['direction'].lower(),
                'strength': strength,
                'entry_time': entry_time.strftime('%Y-%m-%d %H:%M'),
                'entry_price': entry_price,
                'current_price': current_price,
                'unrealized_pct': unrealized_pct,
                'detected_at': datetime.now().isoformat()
            }

    return None


def send_reversal_alert(reversal_info):
    """トレンド反転アラートをGmail送信"""
    symbol_jp = reversal_info['symbol_jp']
    reversal_type = reversal_info['reversal_type']
    strength = reversal_info['strength'] * 100
    entry_time = reversal_info['entry_time']
    entry_price = reversal_info['entry_price']
    new_direction = reversal_info['new_direction']
    
    # 方向の日本語表示
    direction_emoji = "🟢 買い" if new_direction == "buy" else "🔴 売り"
    opposite_emoji = "🔴 売り" if new_direction == "buy" else "🟢 買い"
    
    subject = f"🚨 【緊急】{symbol_jp} トレンド反転検知！"
    
    # include current price and unrealized loss if available
    current_price = reversal_info.get('current_price')
    unrealized_pct = reversal_info.get('unrealized_pct')

    current_price_str = f"{current_price:,.2f}" if current_price is not None else ""
    unrealized_str = f"{unrealized_pct:.2f}%" if unrealized_pct is not None else ""

    body = f"""
🚨 トレンド反転アラート 🚨

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️  {symbol_jp} でトレンド反転を検知しました
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 反転情報:
   反転パターン: {reversal_type}
   新トレンド強度: {strength:.0f}%

📌 あなたのポジション:
   エントリー時刻: {entry_time}
   エントリー価格: {entry_price:,.2f}
   現在価格: {current_price_str}
   未実現損失率: {unrealized_str}
   方向: {opposite_emoji}

🎯 推奨アクション:
   1. 現在のポジションを即座に損切り
   2. 新トレンドに乗る: {direction_emoji}
   3. 損失を新ポジションで取り戻す

⏰ 検知時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💡 このアラートは15分ごとの自動監視で検出されました
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🤖 CFD3 トレンド反転監視システム
"""
    
    # 週末は通知を抑止
    try:
        from datetime import datetime
        if datetime.now().weekday() in (5, 6):
            print(f"⚠️ 週末のため反転アラートをスキップ: {symbol_jp}")
            return False
    except Exception:
        pass

    # Respect environment switch to disable notifications
    notify_enabled = os.environ.get('NOTIFY_ENABLED', '1').lower() not in ('0', 'false', 'no')
    if not notify_enabled:
        print(f"⚠️ 通知は無効化されています (NOTIFY_ENABLED={os.environ.get('NOTIFY_ENABLED')}). 反転アラートは送信されません: {symbol_jp}")
        return False

    # Rate-limit: check how many notifications in last hour and compare to NOTIFY_MAX_PER_HOUR
    try:
        max_per_hour = int(os.environ.get('NOTIFY_MAX_PER_HOUR', '50'))
    except Exception:
        max_per_hour = 50

    # count history entries within last hour
    try:
        if HISTORY_FILE.exists():
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                hist = json.load(f)
        else:
            hist = []
        # use module-level datetime/timedelta imported at top
        cutoff = datetime.now() - timedelta(hours=1)
        recent = 0
        for h in hist:
            try:
                if datetime.fromisoformat(h['detected_at']) > cutoff:
                    recent += 1
            except Exception:
                continue
        if recent >= max_per_hour:
            print(f"⚠️ 反転通知は1時間上限({max_per_hour})に達しています (sent={recent})。送信をスキップ: {symbol_jp}")
            return False
    except Exception:
        # if any error, continue to attempt send
        pass

    try:
        yag = yagmail.SMTP(GMAIL_FROM)
        yag.send(to=GMAIL_TO, subject=subject, contents=body)
        print(f"✅ 反転アラート送信成功: {symbol_jp}")
        return True
    except Exception as e:
        print(f"❌ Gmail送信エラー: {e}")
        return False


def is_already_notified(reversal_info, hours=1):
    """
    同じ反転について過去N時間以内に通知済みかチェック
    
    Args:
        reversal_info: 反転情報
        hours: チェックする時間範囲（デフォルト1時間）
    
    Returns:
        bool: 通知済みならTrue
    """
    if not HISTORY_FILE.exists():
        return False
    
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            history = json.load(f)
    except Exception:
        return False
    
    # チェック対象の時刻
    cutoff_time = datetime.now() - timedelta(hours=hours)
    
    # ユニークキー: 銘柄 + 反転パターン
    current_key = f"{reversal_info['symbol']}_{reversal_info['reversal_type']}"
    
    for past in history:
        detected_at = datetime.fromisoformat(past['detected_at'])
        
        # 期間外は無視
        if detected_at < cutoff_time:
            continue
        
        past_key = f"{past['symbol']}_{past['reversal_type']}"
        
        if current_key == past_key:
            minutes_ago = (datetime.now() - detected_at).total_seconds() / 60
            print(f"   ℹ️  {reversal_info['symbol_jp']}: {minutes_ago:.0f}分前に通知済み - スキップ")
            return True
    
    return False


def save_reversal_history(reversal_info):
    """反転履歴を保存"""
    history = []
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                history = json.load(f)
        except Exception as e:
            # JSON が壊れている可能性があるためバックアップしてリセット
            try:
                corrupt_backup = HISTORY_FILE.with_suffix('.corrupt.' + datetime.now().strftime('%Y%m%d_%H%M%S') + '.json')
                HISTORY_FILE.rename(corrupt_backup)
                print(f"⚠️ 反転履歴ファイルが破損していたためバックアップしました: {corrupt_backup.name}")
            except Exception:
                print("⚠️ 反転履歴のバックアップに失敗しました")
            history = []
    
    history.append(reversal_info)
    
    # 古い履歴を削除（7日以前）
    cutoff = datetime.now() - timedelta(days=7)
    history = [h for h in history if datetime.fromisoformat(h['detected_at']) > cutoff]
    
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def main():
    """メイン処理"""
    print("=" * 60)
    print("🔍 トレンド反転監視システム 起動")
    print("=" * 60)
    
    # ポジション読み込み
    positions = load_positions()
    
    if not positions:
        print("📭 監視対象のポジションがありません")
        return
    
    print(f"📊 監視中のポジション: {len(positions)}件\n")
    
    # 各ポジションをチェック
    reversals = []
    for pos in positions:
        reversal = check_reversal(pos)
        if reversal:
            reversals.append(reversal)
            print(f"🚨 反転検知: {reversal['symbol_jp']} ({reversal['reversal_type']})")
    
    # 反転があればアラート送信
    if reversals:
        print(f"\n⚠️  {len(reversals)}件の反転を検知しました\n")
        for rev in reversals:
            # 重複チェック
            if is_already_notified(rev, hours=1):
                continue
            
            # 新規反転のみ送信
            if send_reversal_alert(rev):
                save_reversal_history(rev)
    else:
        print("\n✅ 反転なし - 現在のポジションは安全です\n")
    
    print("=" * 60)


if __name__ == '__main__':
    main()
