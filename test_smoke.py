#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
スモークテスト — 15分版
各必須ブロックの動作確認（想定アウトカム付き）
"""

import sys
import time
from pathlib import Path

# プロジェクトルートをパスに追加
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "server"))

from server.analyze_unified_ifd import (
    is_time_synced,
    allow_fill,
    should_damp_for_event,
    cooldown_required,
    audit_log_line,
    analyze_unified_ifd
)

print("=" * 80)
print("CFD3 スモークテスト開始")
print("=" * 80)

# ============================================================
# A) 時系列同期ガード
# ============================================================
print("\n[A] 時系列同期ガード (is_time_synced)")
print("-" * 80)

now = time.time()

# A-1: 正常（スクショ時刻=現在±30s、TV/CSV差<60s）
print("\n[A-1] 正常ケース")
synced, reason = is_time_synced(now - 20, now - 10, now - 15)
print(f"  結果: synced={synced}, reason={reason}")
print(f"  期待: synced=True, reason=sync_ok")
print(f"  判定: {'✅ PASS' if synced and reason == 'sync_ok' else '❌ FAIL'}")

# A-2: スクショ古い（+5分）
print("\n[A-2] スクショ古い（5分経過）")
synced, reason = is_time_synced(now - 300, now, now)
print(f"  結果: synced={synced}, reason={reason}")
print(f"  期待: synced=False, reason=vision_stale")
print(f"  判定: {'✅ PASS' if not synced and 'stale' in reason else '❌ FAIL'}")

# A-3: TVとの乖離大
print("\n[A-3] TVとの乖離大（5分差）")
synced, reason = is_time_synced(now - 20, now - 320, now - 15)
print(f"  結果: synced={synced}, reason={reason}")
print(f"  期待: synced=False, reason=vision_tv_skew")
print(f"  判定: {'✅ PASS' if not synced and 'tv_skew' in reason else '❌ FAIL'}")

# A-4: CSVとの乖離大
print("\n[A-4] CSVとの乖離大（5分差）")
synced, reason = is_time_synced(now - 20, now - 10, now - 320)
print(f"  結果: synced={synced}, reason={reason}")
print(f"  期待: synced=False, reason=vision_csv_skew")
print(f"  判定: {'✅ PASS' if not synced and 'csv_skew' in reason else '❌ FAIL'}")

# ============================================================
# B) スリッページ許容
# ============================================================
print("\n\n[B] スリッページ許容 (allow_fill)")
print("-" * 80)

# B-1: 許容範囲内（entry + tol/2）
print("\n[B-1] 許容範囲内")
entry = 49500.0
atr = 100.0
tol_calc = max(entry * 0.0003, atr * 0.2)  # 14.85 or 20.0 = 20.0
last_price = entry + tol_calc / 2  # 49510.0
ok, tol = allow_fill(entry, last_price, atr)
print(f"  entry={entry}, last={last_price}, atr={atr}")
print(f"  結果: ok={ok}, tolerance={tol:.2f}")
print(f"  期待: ok=True")
print(f"  判定: {'✅ PASS' if ok else '❌ FAIL'}")

# B-2: 許容範囲外（entry + 2*tol）
print("\n[B-2] 許容範囲外")
last_price = entry + 2 * tol_calc  # 49540.0
ok, tol = allow_fill(entry, last_price, atr)
print(f"  entry={entry}, last={last_price}, atr={atr}")
print(f"  結果: ok={ok}, tolerance={tol:.2f}")
print(f"  期待: ok=False (リスク半減またはSTOP)")
print(f"  判定: {'✅ PASS' if not ok else '❌ FAIL'}")

# ============================================================
# C) イベント・時間帯ルール
# ============================================================
print("\n\n[C] イベント・時間帯ルール (should_damp_for_event)")
print("-" * 80)

# C-1: 平常・フラグなし
print("\n[C-1] 平常時")
action = should_damp_for_event(now, has_high_impact=False)
print(f"  結果: action={action}")
print(f"  期待: action=OK")
print(f"  判定: {'✅ PASS' if action == 'OK' else '❌ FAIL'}")

# C-2: 高インパクト指標フラグ
print("\n[C-2] 高インパクトイベント")
action = should_damp_for_event(now, has_high_impact=True)
print(f"  結果: action={action}")
print(f"  期待: action=DAMP (risk×0.5)")
print(f"  判定: {'✅ PASS' if action == 'DAMP' else '❌ FAIL'}")

# C-3: 金曜JST 23:00以降（シミュレート）
print("\n[C-3] 金曜23:00以降")
import pytz
import datetime
tz = pytz.timezone("Asia/Tokyo")
# 次の金曜23:30を生成
dt_now = datetime.datetime.now(tz)
days_until_friday = (4 - dt_now.weekday()) % 7
if days_until_friday == 0 and dt_now.hour >= 23:
    days_until_friday = 7
dt_friday = dt_now + datetime.timedelta(days=days_until_friday)
dt_friday = dt_friday.replace(hour=23, minute=30, second=0, microsecond=0)
friday_epoch = dt_friday.timestamp()
action = should_damp_for_event(friday_epoch, has_high_impact=False)
print(f"  テスト時刻: {dt_friday.strftime('%Y-%m-%d %H:%M:%S %Z')}")
print(f"  結果: action={action}")
print(f"  期待: action=STOP")
print(f"  判定: {'✅ PASS' if action == 'STOP' else '❌ FAIL'}")

# ============================================================
# D) 連敗クールダウン
# ============================================================
print("\n\n[D] 連敗クールダウン (cooldown_required)")
print("-" * 80)

# テスト用の監査ログファイルを作成
import json
import tempfile

log_dir = Path(tempfile.mkdtemp())
log_file = log_dir / "test_audit.jsonl"

# D-1: 直近5件で合計 -2.1%（限界超過）
print("\n[D-1] 連敗クールダウン発動（-2.1%）")
pnl_data = [-0.004, -0.006, -0.003, -0.005, -0.003]  # 合計 -2.1%
with open(log_file, "w") as f:
    for i, pnl in enumerate(pnl_data):
        log = {"ts": int(time.time()) - (5 - i) * 60, "sym": "TEST", "realized_pnl_pct": pnl}
        f.write(json.dumps(log) + "\n")

is_cooldown, reason, dd = cooldown_required(log_file, n=5, dd_limit_pct=0.02)
print(f"  PNL: {pnl_data}, 合計: {sum(pnl_data):.3%}")
print(f"  結果: cooldown={is_cooldown}, reason={reason}, dd={dd:.3%}")
print(f"  期待: cooldown=True (全銘柄STOP)")
print(f"  判定: {'✅ PASS' if is_cooldown else '❌ FAIL'}")

# D-2: 直近5件で合計 -1.5%（許容範囲内）
print("\n[D-2] 連敗継続可能（-1.5%）")
pnl_data = [-0.003, -0.004, -0.002, -0.004, -0.002]  # 合計 -1.5%
log_file2 = log_dir / "test_audit2.jsonl"
with open(log_file2, "w") as f:
    for i, pnl in enumerate(pnl_data):
        log = {"ts": int(time.time()) - (5 - i) * 60, "sym": "TEST", "realized_pnl_pct": pnl}
        f.write(json.dumps(log) + "\n")

is_cooldown, reason, dd = cooldown_required(log_file2, n=5, dd_limit_pct=0.02)
print(f"  PNL: {pnl_data}, 合計: {sum(pnl_data):.3%}")
print(f"  結果: cooldown={is_cooldown}, reason={reason}, dd={dd:.3%}")
print(f"  期待: cooldown=False (取引継続)")
print(f"  判定: {'✅ PASS' if not is_cooldown else '❌ FAIL'}")

# ============================================================
# E) 監査ログ
# ============================================================
print("\n\n[E] 監査ログ (audit_log_line)")
print("-" * 80)

print("\n[E-1] 監査ログ生成")
log_line = audit_log_line(
    sym="日本225",
    level="GO",
    score=1.12,
    votes={"buy": 3, "sell": 1},
    rr1=1.7,
    rr2=2.4,
    vol=0.0065,
    gate="sync_ok|DATA_OK",
    event="OK",
    cooldown=False
)
print(f"  生成: {log_line}")
parsed = json.loads(log_line)
print(f"  パース: {parsed}")

# 必須フィールドチェック
required_fields = ["ts", "sym", "level", "score", "rr1", "rr2", "vol", "gate"]
missing = [f for f in required_fields if f not in parsed]
print(f"  期待: 必須フィールド完備")
print(f"  判定: {'✅ PASS' if not missing else f'❌ FAIL (欠損: {missing})'}")

# ============================================================
# F) 統合テスト（簡易版 - GPTスキップ）
# ============================================================
print("\n\n[F] 統合テスト (analyze_unified_ifd)")
print("-" * 80)

print("\n[F-1] 時系列チェックのみ（GPT呼び出しなし）")
print("  ※ 実データでのGPT呼び出しは本番環境でテストしてください")
print("  ※ ここでは時系列同期ガードのロジックを確認")

# 時系列チェックの動作確認
now = time.time()
test_cases = [
    ("日本225", now - 20, "正常", True),
    ("米国NQ100ミニ", now - 400, "stale", False),
]

for symbol, ts, expected_desc, should_pass in test_cases:
    synced, reason = is_time_synced(ts, now - 10, now - 15)
    print(f"\n  {symbol} (ts={int(now-ts)}s前):")
    print(f"    結果: synced={synced}, reason={reason}")
    print(f"    期待: {expected_desc}")
    
    if should_pass:
        result = "✅ PASS" if synced else "❌ FAIL"
    else:
        result = "✅ PASS" if not synced else "❌ FAIL"
    print(f"    判定: {result}")

# ============================================================
# まとめ
# ============================================================
print("\n" + "=" * 80)
print("スモークテスト完了")
print("=" * 80)
print("\n手動確認項目:")
print("  1. logs/audit_YYYYMMDD.jsonl に監査ログが記録されているか")
print("  2. STOP理由が正しく記録されているか（sync_ok/vision_stale等）")
print("  3. risk_multiplier が 0.5 または 1.0 で記録されているか")
print("\n次のステップ:")
print("  - 本番環境で Vision API からの実データでテスト")
print("  - 高インパクトイベント時の動作確認")
print("  - 金曜夜の自動STOP動作確認")
print("=" * 80)
