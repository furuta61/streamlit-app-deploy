#!/usr/bin/env python3
"""
auto_high_accuracy_switch.py

compare_etf_vs_index.py を実行して出力された decision に基づき
自動で高精度モードのフラグを切り替えるヘルパースクリプト。

動作:
  - 比較スクリプトを実行（内部で output/high_accuracy_decision.json を生成）
  - decision を読み、config/high_accuracy.env を更新して USE_HIGH_ACCURACY=0/1 を出力
  - --apply-restart を付けると `./setup_continuous_monitor.sh restart` を実行して反映を試みる

注意: launchd の plist などは外部で環境変数を読み込むようにしてください（例:サービス起動時に `source config/high_accuracy.env` を行うラッパースクリプトを利用）。
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def run_compare(etf: str, index_sym: str, days: int) -> Path:
    """compare_etf_vs_index.py を実行して output/high_accuracy_decision.json を生成する"""
    cmd = [sys.executable, 'scripts/compare_etf_vs_index.py', '--etf', etf, '--index', index_sym, '--days', str(days)]
    print('Running:', ' '.join(cmd))
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as e:
        print('compare script failed:', e)
        raise

    out_path = Path.cwd() / 'output' / 'high_accuracy_decision.json'
    if not out_path.exists():
        raise FileNotFoundError(out_path)
    return out_path


def apply_decision(decision_path: Path, apply_restart: bool = False):
    with open(decision_path, 'r') as f:
        dec = json.load(f)

    decision = dec.get('decision')
    use_flag = '1' if decision == 'use_high_accuracy' else '0'

    cfg_dir = Path.cwd() / 'config'
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = cfg_dir / 'high_accuracy.env'

    with open(cfg_path, 'w') as f:
        f.write(f"USE_HIGH_ACCURACY={use_flag}\n")

    print(f'Wrote {cfg_path} -> USE_HIGH_ACCURACY={use_flag} (decision={decision})')

    if apply_restart:
        # run setup script to restart service (best-effort)
        script = Path.cwd() / 'setup_continuous_monitor.sh'
        if not script.exists():
            print('setup_continuous_monitor.sh not found; skipping restart')
            return
        try:
            subprocess.check_call([str(script), 'restart'])
            print('Service restarted via setup_continuous_monitor.sh')
        except subprocess.CalledProcessError as e:
            print('Failed to restart service:', e)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--etf', default='1321.T')
    p.add_argument('--index', default='^N225')
    p.add_argument('--days', type=int, default=180)
    p.add_argument('--apply-restart', action='store_true', help='If set, call setup_continuous_monitor.sh restart to apply change')
    p.add_argument('--reload-launchd', action='store_true', help='If set, run launchctl unload/load on the provided plist to force launchd to reload (macOS only)')
    p.add_argument('--plist', default='launchd/cfd3_autosystem.continuous.plist', help='Path to plist to unload/load when --reload-launchd is used')
    args = p.parse_args()

    try:
        decision_path = run_compare(args.etf, args.index, args.days)
    except Exception as e:
        print('Error running compare:', e)
        sys.exit(2)

    try:
        apply_decision(decision_path, apply_restart=args.apply_restart)
    except Exception as e:
        print('Error applying decision:', e)
        sys.exit(3)

    # Optional: reload launchd plist to ensure wrapper changes are picked up
    if args.reload_launchd:
        plist_path = Path.cwd() / args.plist
        if not plist_path.exists():
            print(f'Plist not found: {plist_path}; skipping launchd reload')
            sys.exit(0)

        # Only on macOS attempt launchctl unload/load (best-effort)
        try:
            import platform
            if platform.system() != 'Darwin':
                print('Not macOS; cannot reload launchd. Skipping.')
            else:
                print(f'Attempting launchctl unload {plist_path}')
                subprocess.check_call(['launchctl', 'unload', str(plist_path)])
                print(f'Attempting launchctl load {plist_path}')
                subprocess.check_call(['launchctl', 'load', str(plist_path)])
                print('launchd plist reloaded')
        except Exception as e:
            print('launchd reload failed (non-fatal):', e)
            # do not error the whole flow for reload failure

    print('Done')


if __name__ == '__main__':
    main()
