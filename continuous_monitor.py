#!/usr/bin/env python3
"""
continuous_monitor.py
24時間連続監視システム - GMO用6銘柄を監視してストロングGO/GOを即座に通知

実行方法:
    ./.venv/bin/python3 continuous_monitor.py

機能:
- 15分ごとにマーケットデータを取得
- GMO用6銘柄（JP225, NQ100ミニ, ドイツ40, 金, 銀, 天然ガス）を分析
- トレンド分析で買い/売り自動判定
- STRONG_GO または GO シグナルを検出したら即座にGmail通知
- 重複通知を防ぐため、過去の通知履歴を記録
"""
import sys
import os
import time
import subprocess
import glob
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd

ROOT = Path(__file__).resolve().parent
MARKET_DATA_PATH = ROOT / 'market_data.csv'
LOGS_DIR = ROOT / 'logs'
# GMOデイトレ用スクリプトに変更
WEEKLY_SCRIPT = ROOT / 'cfd3_ifd_daytrade.py'
EVENTS_FILE = ROOT / 'events.csv'
NOTIFICATION_LOG = ROOT / 'logs' / 'notification_history.json'

# ==================== 設定 ====================
MONITOR_INTERVAL = 30  # 監視間隔（秒） - 30秒ごとにチェック
FROM_EMAIL = "furuta61@gmail.com"
TO_EMAIL = "furuta61@gmail.com"
TARGET_SIGNALS = ['STRONG_GO']  # 通知対象のシグナル（変更: STRONG_GO のみ通知）

# GMO用6銘柄リスト（SP500は監視対象から除外）
SYMBOLS = ['JP225', 'NASDAQ_MINI', 'DE40', 'GOLD_SPOT', 'SILVER_SPOT', 'NATURAL_GAS']

# 通知を一時的に無効化するフラグ (環境変数で制御)
# 例: export NOTIFY_ENABLED=0
NOTIFY_ENABLED = os.getenv('NOTIFY_ENABLED', '1')
NOTIFY_ENABLED = NOTIFY_ENABLED.lower() not in ('0', 'false', 'no')


def is_weekend() -> bool:
    """週末かどうかを判定（True: 土曜または日曜）"""
    try:
        return datetime.now().weekday() in (5, 6)
    except Exception:
        return False


def log_message(msg: str):
    """タイムスタンプ付きログメッセージ"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] {msg}")


def fetch_market_data():
    """マーケットデータを取得"""
    try:
        from market_data_fetch import fetch_market_data, save_market_data
        log_message("📊 マーケットデータ取得中...")
        df = fetch_market_data(days=1, interval='1h', use_cache=False)
        save_market_data(df, str(MARKET_DATA_PATH))
        log_message(f"✅ マーケットデータ更新完了: {len(df)} rows")
        return True
    except Exception as e:
        log_message(f"⚠️ マーケットデータ取得失敗: {e}")
        return False


def update_realtime_prices(csv_path: Path) -> bool:
    """最新の市場価格でCSVを更新"""
    try:
        log_message("💹 リアルタイム価格取得中...")
        updater_script = ROOT / 'realtime_price_updater.py'
        
        if not updater_script.exists():
            log_message("⚠️ realtime_price_updater.py が見つかりません")
            return False
        
        cmd = [sys.executable, str(updater_script), str(csv_path)]
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=60
        )
        
        if proc.returncode == 0:
            log_message("✅ 価格更新完了")
            return True
        else:
            log_message(f"⚠️ 価格更新エラー (code {proc.returncode})")
            if proc.stderr:
                log_message(f"Error: {proc.stderr[:200]}")
            return False
    except Exception as e:
        log_message(f"❌ 価格更新失敗: {e}")
        return False


def generate_ifd_signals():
    """IFDシグナルを生成（リアルタイム価格使用）"""
    try:
        # realtime_ifd_run.py を使って常に最新価格で分析
        realtime_script = ROOT / 'realtime_ifd_run.py'
        
        if not realtime_script.exists():
            log_message(f"⚠️ {realtime_script} が見つかりません、デイトレスクリプトを使用")
            cmd = [sys.executable, str(WEEKLY_SCRIPT)]
        else:
            log_message("🔄 リアルタイムIFD分析実行中...")
            cmd = [sys.executable, str(realtime_script)]
        
        proc = subprocess.run(
            cmd, 
            cwd=str(ROOT), 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            text=True, 
            check=False,
            timeout=300
        )
        
        if proc.returncode == 0:
            log_message("✅ リアルタイムIFD分析完了")
            return True
        else:
            log_message(f"⚠️ IFD分析エラー (code {proc.returncode})")
            if proc.stderr:
                log_message(f"Error: {proc.stderr[:200]}")
            return False
    except subprocess.TimeoutExpired:
        log_message("⏱️ IFD分析がタイムアウト")
        return False
    except Exception as e:
        log_message(f"❌ IFD分析実行失敗: {e}")
        return False


def get_latest_internal_csv():
    """最新のinternal CSVファイルを取得（Google Driveは参照しない）"""
    try:
        # logsディレクトリの_internal.csvのみを使用（最新データを保証）
        patterns = [str(LOGS_DIR / 'events_scored_*_internal.csv')]
        # 旧来の別ディレクトリ（Desktop の CFD3_AutoSystem/logs）も探索しておく
        patterns.append(str(Path.home() / 'Desktop' / 'CFD3_AutoSystem' / 'logs' / 'events_scored_*_internal.csv'))

        files = []
        for p in patterns:
            files.extend(sorted(glob.glob(p), key=os.path.getmtime))

        if not files:
            log_message(f"⚠️ CSVファイルが見つかりません: {patterns}")
            return None

        latest = files[-1]
        latest_path = Path(latest)
        
        # ファイルの更新時刻を確認（5分以上古い場合は警告）
        file_age_seconds = time.time() - latest_path.stat().st_mtime
        file_age_minutes = file_age_seconds / 60
        
        if file_age_minutes > 5:
            log_message(f"⚠️ 警告: CSVが古い可能性があります（{file_age_minutes:.1f}分前） - {latest_path.name}")
        else:
            log_message(f"✅ 最新CSV確認: {latest_path.name} ({file_age_minutes:.1f}分前)")
        
        return latest
    except Exception as e:
        log_message(f"⚠️ CSV検索エラー: {e}")
        return None


def load_notification_history():
    """通知履歴を読み込み（重複通知防止用）"""
    try:
        if NOTIFICATION_LOG.exists():
            import json
            with open(NOTIFICATION_LOG, 'r', encoding='utf-8') as f:
                history = json.load(f)
                # 24時間以内の履歴のみ保持
                cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
                return {k: v for k, v in history.items() if v > cutoff}
        return {}
    except Exception as e:
        log_message(f"⚠️ 通知履歴読み込みエラー: {e}")
        return {}


def save_notification_history(history: dict):
    """通知履歴を保存"""
    try:
        import json
        LOGS_DIR.mkdir(exist_ok=True)
        with open(NOTIFICATION_LOG, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_message(f"⚠️ 通知履歴保存エラー: {e}")


def create_notification_key(row):
    """通知の一意キーを生成（重複チェック用）"""
    signal_type = "STRONG_GO" if row['combined_score'] >= 0.85 else "GO"
    event_date = row.get('date', row.get('event_date', ''))
    return f"{signal_type}_{row['entry_source']}_{row['entry']:.2f}_{event_date}"


def check_and_notify_signals(csv_path: str, notification_history: dict):
    """シグナルをチェックして、新規のSTRONG_GO/GOがあれば通知"""
    try:
        df = pd.read_csv(csv_path)
        
        # 🆕 銘柄の検証：除外銘柄が含まれていないかチェック
        EXCLUDED_SYMBOLS = ['SP500', 'MSFT', 'AAPL']
        if 'entry_source' in df.columns:
            excluded_found = df['entry_source'].isin(EXCLUDED_SYMBOLS).any()
            if excluded_found:
                excluded_list = df[df['entry_source'].isin(EXCLUDED_SYMBOLS)]['entry_source'].unique().tolist()
                log_message(f"⚠️ 警告: 除外銘柄が検出されました: {excluded_list}")
                log_message(f"⚠️ このCSVは古いデータの可能性があります: {csv_path}")
                # 除外銘柄をフィルタ
                df = df[~df['entry_source'].isin(EXCLUDED_SYMBOLS)]
                log_message(f"✅ 除外銘柄を削除: 残り{len(df)}件")
        
        # 🆕 GMO 6銘柄のみ許可
        ALLOWED_SYMBOLS = SYMBOLS  # ['JP225', 'NASDAQ_MINI', 'DE40', 'GOLD_SPOT', 'SILVER_SPOT', 'NATURAL_GAS']
        if 'entry_source' in df.columns:
            # GMO銘柄名への変換マップ
            SYMBOL_NORMALIZE = {
                'JP225': 'JP225',
                '日本225': 'JP225',
                'NASDAQ_MINI': 'NASDAQ_MINI',
                '米国NQ100ミニ': 'NASDAQ_MINI',
                'DE40': 'DE40',
                'ドイツ40': 'DE40',
                'GOLD_SPOT': 'GOLD_SPOT',
                '金スポット': 'GOLD_SPOT',
                'SILVER_SPOT': 'SILVER_SPOT',
                '銀スポット': 'SILVER_SPOT',
                'NATURAL_GAS': 'NATURAL_GAS',
                '天然ガス': 'NATURAL_GAS'
            }
            # 正規化して検証
            df['normalized_symbol'] = df['entry_source'].map(SYMBOL_NORMALIZE)
            unknown_symbols = df[df['normalized_symbol'].isna()]['entry_source'].unique().tolist()
            if unknown_symbols:
                log_message(f"⚠️ 警告: 未知の銘柄が検出されました: {unknown_symbols}")
            df = df[df['normalized_symbol'].notna()]
            log_message(f"✅ GMO 6銘柄のみ: {len(df)}件")
        
        # STRONG_GO (>=0.85) または GO (>=0.82) のみフィルタ
        tradable = df[(df['combined_score'] >= 0.82) & (df['lot_size'] > 0)]
        
        if len(tradable) == 0:
            log_message("📭 取引可能シグナルなし")
            return notification_history
        
        # 新規シグナルのみ抽出
        new_signals = []
        for _, row in tradable.iterrows():
            key = create_notification_key(row)
            if key not in notification_history:
                new_signals.append(row.to_dict())  # Series を dict に変換
                notification_history[key] = datetime.now().isoformat()
        
        if len(new_signals) == 0:
            log_message(f"📬 既知のシグナル {len(tradable)}件（新規なし）")
            return notification_history
        
        # 新規シグナルがあればGmail通知（ただしレート制限に従う）
        log_message(f"🎯 新規シグナル検出: {len(new_signals)}件")

        # Rate limiting: 環境変数 NOTIFY_MAX_PER_HOUR で1時間当たりの上限を設定
        try:
            max_per_hour = int(os.getenv('NOTIFY_MAX_PER_HOUR', '50'))
        except Exception:
            max_per_hour = 50

        # count notifications in last 1 hour from notification_history
        from datetime import datetime, timedelta
        cutoff = datetime.now() - timedelta(hours=1)
        sent_last_hour = 0
        for k, v in notification_history.items():
            try:
                if datetime.fromisoformat(v) > cutoff:
                    sent_last_hour += 1
            except Exception:
                continue

        remaining = max_per_hour - sent_last_hour
        if remaining <= 0:
            log_message(f"⚠️ 1時間あたりの通知上限に達しています (sent={sent_last_hour}, max={max_per_hour})。今回は通知をスキップします。")
            return notification_history

        # Trim new_signals if they exceed remaining allowance
        if len(new_signals) > remaining:
            log_message(f"⚠️ 今回の新規シグナル {len(new_signals)} 件は上限 {remaining} 件を超えたため、先頭 {remaining} 件のみ通知します。")
            new_signals = new_signals[:remaining]

        send_gmail_notification(new_signals, csv_path)
        
        return notification_history
        
    except Exception as e:
        log_message(f"⚠️ シグナルチェックエラー: {e}")
        return notification_history


def send_gmail_notification(signals: list, csv_path: str):
    """Gmail通知を送信"""
    import traceback
    try:
        # 環境変数で通知を無効化している場合は送信をスキップ
        # 週末は通知を抑止
        if is_weekend():
            log_message("⚠️ 週末のため通知をスキップします")
            return

        if not NOTIFY_ENABLED:
            log_message(f"⚠️ Gmail通知は無効化されています (NOTIFY_ENABLED={os.getenv('NOTIFY_ENABLED')}). {len(signals)}件の通知は送信されません。")
            return
        import yagmail

        # メール本文生成
        strong_count = sum(1 for s in signals if s['combined_score'] >= 0.85)
        go_count = len(signals) - strong_count

        timestamp = datetime.now().strftime('%Y/%m/%d %H:%M')

        body_lines = [
            f"🎯 CFD3 自動トレードシグナル検出",
            f"",
            f"⏰ 検出時刻: {timestamp}",
            f"📊 新規シグナル: {len(signals)}件",
            f"   - STRONG_GO: {strong_count}件 ⭐⭐⭐",
            f"   - GO: {go_count}件 ⭐⭐",
            f"",
            f"📈 シグナル詳細:",
            f""
        ]

        for i, signal in enumerate(signals, 1):
            signal_type = "STRONG_GO" if signal['combined_score'] >= 0.85 else "GO"
            emoji = "⭐⭐⭐" if signal['combined_score'] >= 0.85 else "⭐⭐"
            
            # 方向を取得（buy/sell）
            direction = signal.get('direction', 'buy').lower()
            direction_jp = "🟢 買い" if direction == 'buy' else "🔴 売り"
            
            body_lines.extend([
                f"{i}. {emoji} {signal_type} - {signal['entry_source']} {direction_jp}",
                f"   エントリー: {signal['entry']:.2f}",
                f"   TP: {signal['TP']:.2f} | SL: {signal['SL']:.2f}",
                f"   ロット: {signal['lot_size']:.1f}",
                f"   リスク額: ¥{signal.get('risk_amount', 0):,.0f}",
                f""
            ])

        body_lines.extend([
            f"",
            f"📎 詳細は添付のCSVファイルをご確認ください。",
            f"",
            f"🤖 CFD3 自動監視システム",
            f"   GMO 6銘柄24時間監視中: {', '.join(SYMBOLS)}"
        ])

        body = "\n".join(body_lines)
        subject = f"[CFD3] 🎯 新規シグナル {len(signals)}件検出！"

        # --- Gmail送信: Keychain 経由をまず試し、失敗したら環境変数 GMAIL_APP_PASSWORD を試す ---
        last_exc = None
        try:
            yag = yagmail.SMTP('furuta61@gmail.com')
            yag.send(
                to='furuta61@gmail.com',
                subject=subject,
                contents=body,
                attachments=[csv_path]
            )
            log_message(f"📧 Gmail通知送信成功 (Keychain): {len(signals)}件")
            return
        except Exception as e_keychain:
            last_exc = e_keychain
            log_message(f"⚠️ Keychain経由のGmail送信に失敗: {type(e_keychain).__name__}: {str(e_keychain)}")
            log_message("   Keychain未設定または認証エラーの可能性があります。フォールバックを試みます...")

        # フォールバック: 環境変数 GMAIL_APP_PASSWORD を使う
        try:
            app_pw = os.environ.get('GMAIL_APP_PASSWORD')
            if app_pw:
                yag = yagmail.SMTP('furuta61@gmail.com', password=app_pw)
                yag.send(
                    to='furuta61@gmail.com',
                    subject=subject,
                    contents=body,
                    attachments=[csv_path]
                )
                log_message(f"📧 Gmail通知送信成功 (env GMAIL_APP_PASSWORD): {len(signals)}件")
                return
            else:
                log_message("⚠️ 環境変数 GMAIL_APP_PASSWORD が設定されていません。" )
        except Exception as e_env:
            last_exc = e_env
            log_message(f"⚠️ 環境変数経由のGmail送信に失敗: {type(e_env).__name__}: {str(e_env)}")

        # 最後に詳細なトレースを出力してユーザーにアクションを促す
        log_message(f"⚠️ Gmail送信最終失敗: {type(last_exc).__name__ if last_exc else 'Unknown'}: {str(last_exc) if last_exc else ''}")
        log_message(f"   詳細: {traceback.format_exc()}")
        log_message("   Keychainの設定を確認してください。Keychainが使えない場合はアプリパスワードを環境変数に設定してください:")
        log_message('   export GMAIL_APP_PASSWORD="<your_app_password>"')
        log_message('   または: python3 -c "import yagmail; yagmail.register(\'furuta61@gmail.com\', \'アプリパスワード\')"')

    except Exception as e:
        # ここは yagmail モジュールが無いなどの致命的エラーを捕捉
        log_message(f"⚠️ Gmail送信準備で致命的エラー: {type(e).__name__}: {str(e)}")
        log_message(f"   詳細: {traceback.format_exc()}")


def monitoring_cycle():
    """1回の監視サイクルを実行"""
    log_message("=" * 60)
    log_message("🔍 監視サイクル開始")
    
    # 通知履歴読み込み
    notification_history = load_notification_history()
    
    # 1. マーケットデータ取得
    if not fetch_market_data():
        log_message("⚠️ マーケットデータ取得失敗、スキップ")
        return notification_history
    
    time.sleep(2)  # データ安定化待ち
    
    # 2. IFDシグナル生成
    if not generate_ifd_signals():
        log_message("⚠️ IFD生成失敗、スキップ")
        return notification_history
    
    time.sleep(1)
    
    # 3. 最新CSVチェック
    latest_csv = get_latest_internal_csv()
    if not latest_csv:
        log_message("⚠️ 最新CSVが見つかりません")
        return notification_history
    
    log_message(f"📄 分析ファイル: {Path(latest_csv).name}")
    
    # 🆕 4. リアルタイム価格更新（重要！）
    update_realtime_prices(Path(latest_csv))
    
    # 5. シグナルチェック＆通知
    notification_history = check_and_notify_signals(latest_csv, notification_history)
    
    # 6. 自動ポジション追跡（過去24時間の通知から抽出）
    try:
        log_message("📊 ポジション自動追跡中...")
        tracker_script = ROOT / 'auto_position_tracker.py'
        if tracker_script.exists():
            cmd = [sys.executable, str(tracker_script)]
            subprocess.run(cmd, cwd=str(ROOT), check=False, timeout=60, 
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            log_message("⚠️ auto_position_tracker.py が見つかりません")
    except Exception as e:
        log_message(f"⚠️ ポジション追跡エラー: {e}")
    
    # 7. トレンド反転監視（既存ポジションを守る）
    try:
        log_message("🔍 トレンド反転チェック中...")
        reversal_script = ROOT / 'trend_reversal_monitor.py'
        if reversal_script.exists():
            cmd = [sys.executable, str(reversal_script)]
            subprocess.run(cmd, cwd=str(ROOT), check=False, timeout=120)
        else:
            log_message("⚠️ trend_reversal_monitor.py が見つかりません")
    except Exception as e:
        log_message(f"⚠️ 反転チェックエラー: {e}")
    
    # 8. 通知履歴保存
    save_notification_history(notification_history)
    
    log_message("✅ 監視サイクル完了")
    return notification_history


def main():
    """メインループ - 24時間連続監視"""
    log_message("🚀 CFD3 24時間監視システム起動")
    log_message(f"📊 監視対象: {', '.join(SYMBOLS)}")
    log_message(f"⏱️ チェック間隔: 30秒")
    log_message(f"🎯 通知対象: {', '.join(TARGET_SIGNALS)}")
    log_message("=" * 60)
    
    cycle_count = 0
    
    try:
        while True:
            cycle_count += 1
            log_message(f"🔄 監視サイクル #{cycle_count}")
            
            try:
                monitoring_cycle()
            except Exception as e:
                log_message(f"❌ 監視サイクルエラー: {e}")
                import traceback
                log_message(traceback.format_exc())
            
            # 次のサイクルまで待機
            next_check = datetime.now() + timedelta(seconds=MONITOR_INTERVAL)
            log_message(f"💤 次回チェック: {next_check.strftime('%H:%M:%S')} ({MONITOR_INTERVAL // 60}分後)")
            log_message("=" * 60)
            
            time.sleep(MONITOR_INTERVAL)
            
    except KeyboardInterrupt:
        log_message("\n⏹️ 監視システム停止（ユーザー操作）")
        return 0
    except Exception as e:
        log_message(f"❌ 予期しないエラー: {e}")
        import traceback
        log_message(traceback.format_exc())
        return 1


if __name__ == '__main__':
    sys.exit(main())
