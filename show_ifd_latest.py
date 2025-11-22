#!/usr/bin/env python3
"""
show_ifd_latest.py
最新のIFD注文を見やすく表示（トレード実行用）
"""
import pandas as pd
import glob
import os
from datetime import datetime
from tabulate import tabulate

# 最新の internal CSV を自動検出して読み込み（logs と output の両方を確認）
files_internal = glob.glob("logs/events_scored_*_internal.csv")
files_output = glob.glob("output/events_scored_*.csv")
files = sorted(files_internal + files_output, key=os.path.getmtime)

if not files:
    print("❌ scored CSV が見つかりませんでした。")
    print("💡 先に realtime_ifd_run.py を実行してください。")
    exit(1)

latest = files[-1]
file_time = datetime.fromtimestamp(os.path.getmtime(latest))
print(f"\n{'='*80}")
print(f"📊 最新のIFD注文 - トレード実行用")
print(f"{'='*80}")
print(f"📁 ファイル: {latest}")
print(f"🕐 生成時刻: {file_time.strftime('%Y-%m-%d %H:%M:%S')}")
print(f"{'='*80}\n")

df = pd.read_csv(latest)

# STRONG_GO と GO のみをフィルタ（type列がある場合）
if 'type' in df.columns:
    trade_df = df[df['type'].isin(['STRONG_GO', 'GO'])].copy()
else:
    # type列がない場合はcombined_scoreで判定（0.8以上をトレード対象）
    trade_df = df[df['combined_score'] >= 0.8].copy()
    # typeを推測（0.9以上=STRONG_GO、それ以外=GO）
    trade_df['type'] = trade_df['combined_score'].apply(lambda x: 'STRONG_GO' if x >= 0.9 else 'GO')

if trade_df.empty:
    print("⚠️  トレード可能なシグナルがありません（STRONG_GO / GO なし）")
    print("\n📋 全シグナル:")
    # 利用可能な列のみ表示
    display_cols = []
    for col in ['text', 'signal', 'type', 'combined_score']:
        if col in df.columns:
            display_cols.append(col)
    print(tabulate(df[display_cols], 
                   headers="keys", tablefmt="fancy_grid", showindex=False))
    exit(0)

print(f"✅ トレード可能なシグナル: {len(trade_df)} 件\n")

# トレード実行に必要な情報を整形
for idx, row in trade_df.iterrows():
    signal_emoji = "🟢" if row['signal'] == 'BUY' else "🔴"
    type_emoji = "⭐" if row['type'] == 'STRONG_GO' else "🟢"
    
    print(f"{type_emoji} {row['type']} | {signal_emoji} {row['signal']}")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"📰 イベント: {row['text']}")
    print(f"📅 日時: {row['date']}")
    print(f"📊 スコア: {row['combined_score']:.2f}")
    print(f"\n💰 トレード設定:")
    print(f"  🎯 市場: {row['entry_source']}")
    print(f"  📍 エントリー: {row['entry']:.2f}")
    print(f"  ✅ 利確 (TP): {row['TP']:.2f}  (+{row['TP']-row['entry']:.2f})")
    print(f"  ❌ 損切 (SL): {row['SL']:.2f}  ({row['SL']-row['entry']:.2f})")
    print(f"  📦 ロット: {row['lot_size']:.2f}")
    print(f"  💵 リスク額: {row['risk_amount']:.2f} 円")
    
    # リスクリワード比を計算
    risk = abs(row['entry'] - row['SL'])
    reward = abs(row['TP'] - row['entry'])
    rr_ratio = reward / risk if risk > 0 else 0
    print(f"  ⚖️  リスクリワード比: 1:{rr_ratio:.2f}")
    
    print(f"\n")

print(f"{'='*80}")
print(f"📋 サマリーテーブル")
print(f"{'='*80}\n")

# コンパクトな表形式でも表示
cols = ["signal", "type", "entry_source", "entry", "TP", "SL", "lot_size", "combined_score"]
display_cols = [c for c in cols if c in trade_df.columns]
print(tabulate(trade_df[display_cols], headers="keys", tablefmt="fancy_grid", showindex=False, floatfmt=".2f"))

print(f"\n💡 次のステップ:")
print(f"  1. 上記のエントリー価格、TP、SLを確認")
print(f"  2. 取引プラットフォームでIFD注文を設定")
print(f"  3. ロットサイズとリスク額を確認して注文実行")
print(f"\n⚠️  注意: 実際の取引前に市場状況を必ず確認してください！\n")
