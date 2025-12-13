#!/usr/bin/env python3
"""
簡易精度評価スクリプト
出力:
 - output/ifd_precision_report.json (summary per instrument)
 - output/ifd_precision_details.csv (各サンプルの結果)

ロジック:
 - `output/ifd_proposals.json` を読み、各 order の entry/tp/sl を取得
 - data フォルダ内の CSV を探索して instrument 名を含むファイルを読み込む
 - CSV 内で entry に近い close 値が出現した箇所を見つけ、その後 K バーで TP/SL のどちらが先に到達するか判定
 - 集計して precision (wins / (wins+losses)) 等を出力
"""
import json
import glob
import os
from pathlib import Path
import math
import pandas as pd
from datetime import datetime


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / 'output'
DATA_DIR = ROOT / 'data'


def find_csv_for_instrument(instr):
    # case-insensitive search for files that contain instrument name
    pattern = str(DATA_DIR / '**' / f'*{instr}*.csv')
    matches = glob.glob(pattern, recursive=True)
    if matches:
        return matches[0]
    # fallback: try uppercase/lower
    pattern = str(DATA_DIR / '**' / f'*{instr.lower()}*.csv')
    matches = glob.glob(pattern, recursive=True)
    return matches[0] if matches else None


def load_csv(path):
    df = pd.read_csv(path)
    # expect columns: time,open,high,low,close
    for c in ['high','low','close']:
        if c not in df.columns:
            raise ValueError(f"CSV {path} missing column {c}")
    return df


def evaluate_order_on_csv(df, entry, tp, sl, max_samples=200, lookahead=24, tol_pct=0.001):
    """
    df: pandas dataframe with high/low/close
    returns list of dicts per sample: outcome: WIN/LOSS/NONE, indices for tp/sl
    """
    samples = []
    entry = float(entry)
    tp = float(tp)
    sl = float(sl)
    tol = max(0.0001 * abs(entry), tol_pct * abs(entry))

    close = df['close'].astype(float)
    # find candidate indices where close approx equals entry
    cand_idx = close[ (close >= entry - tol) & (close <= entry + tol) ].index.tolist()
    if not cand_idx:
        # relax tolerance gradually
        tol2 = tol * 5
        cand_idx = close[ (close >= entry - tol2) & (close <= entry + tol2) ].index.tolist()

    for idx in cand_idx[:max_samples]:
        window = df.iloc[idx+1: idx+1+lookahead]
        tp_idx = None
        sl_idx = None
        for j, row in enumerate(window.itertuples(), start=1):
            high = float(row.high)
            low = float(row.low)
            if tp_idx is None and high >= tp:
                tp_idx = idx + j
            if sl_idx is None and low <= sl:
                sl_idx = idx + j
            if tp_idx is not None and sl_idx is not None:
                break

        if tp_idx is not None and (sl_idx is None or tp_idx <= sl_idx):
            outcome = 'WIN'
        elif sl_idx is not None and (tp_idx is None or sl_idx < tp_idx):
            outcome = 'LOSS'
        else:
            outcome = 'NONE'

        samples.append({
            'sample_index': int(idx),
            'entry': entry,
            'tp': tp,
            'sl': sl,
            'tp_index': int(tp_idx) if tp_idx is not None else None,
            'sl_index': int(sl_idx) if sl_idx is not None else None,
            'outcome': outcome
        })

    return samples


def main():
    prop_path = OUTPUT_DIR / 'ifd_proposals.json'
    if not prop_path.exists():
        print('missing proposals:', prop_path)
        return

    with open(prop_path, 'r') as f:
        proposals = json.load(f)

    orders = proposals.get('orders', [])

    all_summary = {}
    details = []

    for order in orders:
        instr = order.get('instrument')
        decision = order.get('decision','')
        # focus on STRONG_GO and GO (but user asked precision; include STRONG_GO primary)
        if decision not in ('STRONG_GO', 'GO', 'STRONG_STOP'):
            continue

        entry = order.get('entry_price')
        # take first leg TP/SL
        legs = order.get('ifd_legs', [])
        if not legs:
            continue
        tp = legs[0].get('oco', {}).get('take_profit', {}).get('price')
        sl = legs[0].get('oco', {}).get('stop_loss', {}).get('price')
        if entry is None or tp is None or sl is None:
            continue

        csv_path = find_csv_for_instrument(instr)
        if not csv_path:
            print('no csv for', instr)
            all_summary[instr] = {'samples':0,'wins':0,'losses':0,'none':0}
            continue

        df = load_csv(csv_path)
        samples = evaluate_order_on_csv(df, entry, tp, sl, max_samples=200, lookahead=24)

        wins = sum(1 for s in samples if s['outcome']=='WIN')
        losses = sum(1 for s in samples if s['outcome']=='LOSS')
        none = sum(1 for s in samples if s['outcome']=='NONE')
        total = len(samples)
        precision = wins / (wins + losses) if (wins + losses) > 0 else None

        all_summary[instr] = {
            'instrument': instr,
            'decision': decision,
            'csv_used': os.path.relpath(csv_path, ROOT),
            'samples': total,
            'wins': wins,
            'losses': losses,
            'none': none,
            'precision': precision
        }

        for s in samples:
            row = {
                'instrument': instr,
                'decision': decision,
                'csv': os.path.relpath(csv_path, ROOT),
                'sample_index': s['sample_index'],
                'entry': s['entry'],
                'tp': s['tp'],
                'sl': s['sl'],
                'tp_index': s['tp_index'],
                'sl_index': s['sl_index'],
                'outcome': s['outcome']
            }
            details.append(row)

    # write outputs
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = OUTPUT_DIR / 'ifd_precision_report.json'
    details_path = OUTPUT_DIR / 'ifd_precision_details.csv'

    with open(report_path, 'w') as f:
        json.dump({'generated_at': datetime.utcnow().isoformat()+'Z', 'summary': all_summary}, f, indent=2, ensure_ascii=False)

    if details:
        df_details = pd.DataFrame(details)
        df_details.to_csv(details_path, index=False)
    else:
        # write empty
        pd.DataFrame(details).to_csv(details_path, index=False)

    print('Wrote', report_path, 'and', details_path)


if __name__ == '__main__':
    main()
