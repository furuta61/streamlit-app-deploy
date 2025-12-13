# A/B実験結果サマリー

## 実施内容

過去の会話で実装した **ニュース統合 + 閾値調整 + 極端変動ボーナス** の効果を検証するため、新旧設定でA/Bバックテストを試みました。

## 実験設計

### 旧設定 (Old)
- `TECH_WEIGHT=1.0`, `NEWS_WEIGHT=0.0`
- `GO_THRESHOLD=4.0`, `STRONG_GO_THRESHOLD=6.0`
- 極端変動ボーナス無し

### 新設定 (New)
- `TECH_WEIGHT=0.6`, `NEWS_WEIGHT=0.4`
- `GO_THRESHOLD=3.8`, `STRONG_GO_THRESHOLD=5.5`
- 極端変動ボーナス有効

## 実験手法と制約

### 手法1: TradingViewログからのリプレイ (`scripts/ab_backtest.py`)

- `output/tradingview.jsonl` (35件)を利用し、新旧設定で再生成してバックテスト。
- **制約**:
  - TVログには `change_pct` や `screener` データが含まれていないため、極端変動ボーナスやRSI補正が発動しない。
  - ニュースをnews_items=[]に固定したため、NEWS_WEIGHTの効果も無効化。
  - 結果、新旧で同じ34件・同一メトリクスとなり差異なし。

### 手法2: 既存IFDログの閾値再分類 (`scripts/compare_threshold.py`)

- `output/ifd_orders.jsonl` (160件)を新旧閾値で再分類してバックテスト。
- **制約**:
  - 既存ログに `rating` フィールドが含まれていないため、再分類が不可能。
  - 結果、新旧とも157件で一致し、メトリクスもほぼ同一。

## 結果サマリー

### 現在の設定(新)でのバックテスト成績

| 指標             | 値      |
|------------------|---------|
| Total Trades     | 160     |
| Win Rate         | 0.525   |
| Profit Factor    | 2.914   |
| Total Return     | 3.462   |
| Max Drawdown     | -0.1485 |
| Avg Win          | 0.0274  |
| Avg Loss         | -0.0094 |

### 旧/新閾値比較 (rating無しログでの再分類)

| 指標           | 旧 (GO≥4.0) | 新 (GO≥3.8) | 差分    |
|----------------|-------------|-------------|---------|
| Trades         | 157         | 157         | 0       |
| Win Rate       | 0.5287      | 0.5287      | +0.0000 |
| Profit Factor  | 2.9166      | 2.9160      | -0.0006 |
| Total Return   | 3.5263      | 3.5247      | -0.0016 |

→ **実質的な差異なし**(rating欠落のため)

## 結論と今後の推奨

### 現状のまとめ

1. **新設定で運用中の成績は良好**: PF 2.91、勝率52.5%、累計リターン346%（シミュレーション上）
2. **旧設定との定量比較は不完全**: 利用可能なデータに `rating` や `change_pct` が含まれていないため、閾値変更や極端ボーナスの効果を直接測定できませんでした。

### 今後の推奨アクション

1. **rating付きログの蓄積**
   - 現在の設定(`NEWS_WEIGHT=0.4`, `GO=3.8`, `STRONG_GO=5.5`)で運用を続け、`rating`, `news_refs`, `sentiment_score`を含むIFDログを蓄積。
   - 1〜2週間後にrating付きログを用いた再評価を実施。

2. **定期バックテスト**
   - `app/backtest.py` を週次で実行し、主要メトリクスをトラッキング。
   - 劣化が見られた場合は閾値やNEWS_WEIGHTを微調整。

3. **長期A/Bテスト**
   - rating付きログが十分に集まった段階で、`scripts/compare_threshold.py` を再実行。
   - 旧閾値(4.0/6.0)で再分類した場合の採用率・パフォーマンス差を測定。

## 生成ファイル

- `scripts/ab_backtest.py`: TVログリプレイ&バックテスト
- `scripts/compare_threshold.py`: 既存IFDログの閾値再分類比較
- `output/backtest/threshold_compare.md`: 閾値比較レポート
- `output/backtest/ab_metrics.json`: A/B実験メトリクス(両シナリオ同一だったため有意差なし)

---

**最終判断**: 現在の設定(新)は、利用可能なデータで測定した範囲では **良好なパフォーマンス**(PF ~2.9, 勝率 ~53%)を示しています。旧設定との直接比較は、rating付きログが蓄積された後に実施することで、より正確な効果測定が可能になります。
