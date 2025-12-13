# TradingView → CSV 同期 と ブローカースケール適用

このドキュメントは、TradingView webhook ログ（`output/tradingview.jsonl`）を canonical CSV に反映する方法と、IFD 出力にブローカー固有の表示単位（小数桁・スケール）を適用する手順をまとめたものです。

ファイル追加
- `configs/broker_price_map.yaml` — 銘柄ごとの display_decimals / tick / scale_factor を定義
- `scripts/tv_to_csv_sync.py` — `output/tradingview.jsonl` を読み、`data/<SYMBOL>_240.csv` に timestamp,price を追加
- `scripts/apply_broker_scale.py` — `output/ifd_proposals.json` を読み、`configs/broker_price_map.yaml` に基づき価格をスケール／丸めして出力

基本ワークフロー
1. TradingView webhook が到着すると `output/tradingview.jsonl` に行が追加されます。
2. 定期実行（または手動）で `scripts/tv_to_csv_sync.py` を動かし、`data/` 下の CSV を最新化します。例：

```bash
python scripts/tv_to_csv_sync.py --input output/tradingview.jsonl --outdir data
```

3. IFD を生成する通常フロー（例: `python cfd3_portfolio_update_v2.py`）は、canonical CSV を参照して計算します。
4. IFD 表示をブローカー単位に整形するには、`scripts/apply_broker_scale.py` を実行します。例：

```bash
# 出力ファイルを別名で作る（安全）
python scripts/apply_broker_scale.py --input output/ifd_proposals.json --output output/ifd_proposals_broker_scaled.json

# 直接上書きする場合（バックアップを作ります）
python scripts/apply_broker_scale.py --input output/ifd_proposals.json --inplace
```

設定例
- `configs/broker_price_map.yaml` の `scale_factor` は観測に基づく補正係数です。初期値は手動で入れていますが、監査して自動調整することも可能です。

運用上の注意
- 本ツールは安全性優先で設計されていますが、`--inplace` を使うと既存ファイルを上書きします。必ずバックアップを取り、差分を確認してください。
- 恒久的対策としては、TV webhook → CSV 同期を信頼できる形で自動化（cron/launchd + ログ監視）し、スケール係数は運用中に少しずつ調整・記録してください。

cron/launchd の簡単な例
- 毎分実行（cron）例：

```
# crontab -e
* * * * * cd /path/to/CFD3_AutoSystem && /usr/bin/env python3 scripts/tv_to_csv_sync.py --input output/tradingview.jsonl --outdir data >> logs/tv_sync.log 2>&1
```

次のステップ提案
- 1) 少量の履歴データで dry-run を実行して、scale_factor と display_decimals が期待どおりに働くことを確認する。
- 2) `cfd3_portfolio_update_v2.py` に hook を追加し、出力生成時に自動でスケール適用する（慎重にテストする）。
- 3) scale_factor を自動推定するスクリプト（過去X件の比率の中央値を使う等）を作る。
