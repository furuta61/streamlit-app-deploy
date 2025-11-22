# 📊 CFD3 24時間連続監視システム セットアップガイド

## 🎯 システム概要

このシステムは、**7銘柄を24時間365日監視**し、STRONG_GOまたはGOシグナルを検出すると**即座にGmail通知**を送信します。

> ⚠️ 重要 — Gmail の送信上限に達した場合の注意
>
> もし Gmail の「1日あたりの送信上限（500通など）」に達すると、アカウントは一時的にメール送信を受け付けなくなります（通常24時間でリセットされます）。その間に自動監視をそのまま稼働させると、失敗が繰り返されログが溜まり、Keychain や通知履歴に不要なエントリが残る場合があります。
>
> 対処（今すぐ安全に停止／抑止する方法）:
> - すぐに自動通知を止めたい場合（推奨）:
>   1) 監視プロセスを停止:
>
>      ```bash
>      cd '/Users/otomi/Desktop/vs code/CFD3_AutoSystem'
>      ./setup_continuous_monitor.sh stop
>      ```
>
>   2) メール送信のみ無効にする（再起動不要、環境変数で制御）:
>
>      ```bash
>      # シェルで一時的に無効化（そのシェルで実行するコマンドに反映）
>      export NOTIFY_ENABLED=0
>
>      # launchdなどでサービス化している場合は plist に環境変数を追加するか
>      # setup_continuous_monitor.sh を使って再設定してください。
>      ```
>
> - Gmail が復旧（24時間経過）したら通知を再開:
>   ```bash
>   # 通知を有効にして再起動
>   export NOTIFY_ENABLED=1
>   ./setup_continuous_monitor.sh start
>   ```
>
> 参考: 本リポジトリの `continuous_monitor.py` は環境変数 `NOTIFY_ENABLED` を見ており、`0` / `false` / `no` 相当の値を設定するとメール送信をスキップします。


### 監視対象銘柄
1. **JP225** (日経225)
2. **DE40** (ドイツDAX40)
3. **NASDAQ_MINI** (NASDAQ100ミニ)
4. **AAPL** (Apple株)
5. **MSFT** (Microsoft株)
6. **GOLD_SPOT** (金スポット)

### データソース（JP225 の取り扱い）

- 本システムでは JP225（日経225）については**ETF（例: 1321 / 1330）を一次ソース**として扱います。Twelve Data や yfinance の API ではインデックス表記がプロバイダ毎に異なるため、ETF を使うことで取得の安定性と再現性が向上します。
- 優先順位（デフォルト）:
   1. Twelve Data / paid fetcher: `1321`（Twelve Data の表記）
   2. yfinance / ローカル取得: `1321.T`（yfinance 用ティッカー）
   3. その他 ETF（`1330` など）またはインデックス表記（最終フォールバック）
- 監視および分析ロジックは ETF を前提に設計されています。もし公式の「インデックス値（JPX発行）」が必須で、ETF との差が許容できない場合は JPX / QUICK 等の公式データ契約を検討してください。
- システムの挙動を変更したい場合（例: 別ETFを一次ソースにしたい、あるいはインデックスを優先したい）は環境変数で上書きできます:

```bash
# Twelve Data 側で使用するシンボルを明示的に指定
export PAID_SYMBOL_JP225="1321"

# yfinance 側のシンボルをオーバーライドする場合
# (realtime_price_updater.py / trend_analyzer.py はデフォルトで 1321.T を使用します)
export YF_SYMBOL_JP225="1321.T"
```

- 推奨: まず ETF（1321）を一次で運用し、`scripts/compare_etf_vs_index.py` を用いて過去数ヶ月の乖離（平均差 / 最大差 / 相関）を評価してください。乖離が小さければ ETF を本番データとして採用して問題ありません。

### 公式フィード（JPX）導入手順（推奨：最高精度）

ETF による運用で乖離が大きい（または公式値を厳密に使う必要がある）場合は、JPX や QUICK 等の「公式商用インデックスフィード」を導入することを強く推奨します。以下は JPX のような公式フィードを導入して `continuous_monitor` に組み込むための手順（運用者向け）です。

1) 事前準備（契約）
   - JPX/QUICK 等と商用データ契約を締結してください。料金・再配布条件・用途制限（社内利用・公開可否）を必ず確認します。
   - 契約後、開発用 API 情報（エンドポイント、APIキー、シークレット、証明書等）を取得します。

2) 環境変数の設定（安全な方法で）
   - 取得したキー類は環境変数に設定してシステムに渡します（例）：

```bash
export JPX_API_URL="https://api.vendor.example/v1/price"
export JPX_API_KEY="your_api_key_here"
export JPX_API_SECRET="your_api_secret_if_any"
# もしプロバイダ側でインデックスコードが異なる場合は、環境変数で上書きしてください。
export OFFICIAL_SYMBOL_JP225="N225"
# ensemble で公式を優先する
export USE_OFFICIAL=1
```

3) リポジトリ側の設定
   - 既存の `market_data_official.py` はテンプレート実装です。実際のプロバイダの API レスポンス形式に合わせて `fetch_price` のパースを修正してください（例: JSON のキーが `price` か `last` かなど）。

4) 動作確認（ローカル）
   - まずは CLI で単発テスト:

```bash
cd '/Users/otomi/Desktop/vs code/CFD3_AutoSystem'
# 公式モジュールの簡易テスト
./.venv/bin/python3 market_data_official.py JP225

# ensemble 経由で公式が優先されるか確認
./.venv/bin/python3 market_data_ensemble.py JP225
```

   - 期待される戻り値: JSON で `price` を含むオブジェクト（`confidence` は 1.0 扱いで ensemble により即時反映されます）。

5) 運用時の注意
   - ライセンス: 公式データの再配布や通知メールへの添付については契約条件で制限されることがあります。通知や添付で公式値を第三者へ渡す前に契約を確認してください。
   - 可用性: 公式 API がダウンした場合に備え、`market_data_ensemble.py` のフォールバック（ETF アンサンブル）を残しておくと安全です。環境変数 `USE_OFFICIAL` で切替可能です。
   - ロギング: 公式フィードを採用する場合でも `output/ensemble_log.jsonl` に取得結果を残す運用を推奨します（監査・差分解析用）。

6) テスト/移行計画（推奨）
   - まず 7〜14 日間、公式フィードと現在の ETF アンサンブルを並列稼働させ、`scripts/ab_test_generate_signals.py` と `scripts/compare_etf_vs_index.py` で差分・仮想 P/L を評価します。
   - 十分な一致と運用上の納得が得られたら `USE_OFFICIAL=1` を永続化して本番運用に移行してください。

必要であれば、私が `market_data_official.py` をあなたが受け取った JPX のレスポンスサンプルに合わせてパース実装します（サンプルは JSON のキー構造のみで十分。APIキー等の秘密情報は共有しないでください）。

### 乖離（差分）が閾値を超える場合の意味と対処

- 「乖離が閾値を超える」とは、`scripts/compare_etf_vs_index.py` が過去の終値を比較した結果、事前に定めた閾値（平均差や最大差）を上回ったことを意味します。これは「ETF（1321 等）の価格が公式インデックスに対して統計的にずれがある可能性」があるサインです。
- 推奨デフォルト閾値（目安）:
   - 平均差（mean_abs_pct）: 0.5%（この値を超えると注意）
   - 最大差（max_abs_pct）: 1.5%（この値を超えると高精度モードを検討）

- 運用上の意味と推奨アクション:
   1. mean <= 0.5% && max <= 1.5% → ETF を一次ソースとして継続して問題ない（default）。
   2. mean > 0.5% または max > 1.5% → "高精度モード" を有効化して複数ソースのアンサンブル取得（中央値）で価格を確定することを推奨します。これにより単一プロバイダのブレを緩和できます。
   3. それでも乖離が解消しない場合 → JPX / QUICK 等の公式商用フィード取得（契約）を検討してください。

- システムでの実装済み機能（今回の変更）:
   - `scripts/compare_etf_vs_index.py` が比較結果を `output/high_accuracy_decision.json` に書き出します。decision が `use_high_accuracy` の場合は高精度対応を検討してください。
   - 高精度モードの取得ロジックは `market_data_ensemble.py` に実装されています。複数ソース（Twelve Data の ETF、yfinance の ETF）を取得して中央値をとり、`confidence`（0-1）を付与します。
   - 実行時に環境変数 `USE_HIGH_ACCURACY=1` を設定すると、`realtime_price_updater.py` と `trend_analyzer.py` が JP225 に対してアンサンブル取得を優先します（自動化は後述）。

- 環境変数での制御例:

```bash
# 高精度モード（手動切替）
export USE_HIGH_ACCURACY=1

# 比較スクリプトの閾値を上書きしたい場合（%で指定）
export ETF_MEAN_THRESHOLD_PCT=0.5
export ETF_MAX_THRESHOLD_PCT=1.5
```

上記の閾値は運用要件に応じて調整してください（例: 超低スリッページが必須であれば閾値を小さくする）。


### システムの特徴
- ⏱️ **15分ごと**に自動チェック（1日96回）
- 🎯 **STRONG_GO（スコア0.85以上）**のみを通知（設定で変更可能）
- 📧 **即座にGmail通知**（CSVファイル添付付き）
- 🔄 **重複通知を防止**（24時間以内の同一シグナルは通知しない）
- 🚀 **macOS起動時に自動起動**
- 💪 **プロセス監視・自動再起動**（エラー時も継続）

---

## 📦 セットアップ手順

### ステップ1: Gmail通知の設定（初回のみ）

Gmail通知を有効にするため、Googleアプリパスワードを設定します：

#### 1.1 Googleアカウントでアプリパスワードを取得

1. [Googleアカウント](https://myaccount.google.com/)にアクセス
2. **セキュリティ** → **2段階認証プロセス**を有効化
3. **アプリパスワード**を選択
4. アプリを選択: **メール**、デバイスを選択: **Mac**
5. **16桁のパスワード**が表示されます（例: `abcd efgh ijkl mnop`）

#### 1.2 yagmailにアプリパスワードを登録

```bash
cd '/Users/otomi/Desktop/vs code/CFD3_AutoSystem'
./.venv/bin/python3 -c "import yagmail; yagmail.register('furuta61@gmail.com', 'アプリパスワード16桁')"
```

✅ **成功メッセージ**: `Password stored in keychain`

---

### ステップ2: システムのインストール

```bash
cd '/Users/otomi/Desktop/vs code/CFD3_AutoSystem'
./setup_continuous_monitor.sh install
```

これにより：
- ✅ launchdに自動起動サービスを登録
- ✅ macOS起動時に自動的に監視開始
- ✅ プロセス監視（異常終了時は自動再起動）

---

### ステップ3: 動作確認

#### 3.1 ステータス確認
```bash
./setup_continuous_monitor.sh status
```

#### 3.2 リアルタイムログ表示
```bash
./setup_continuous_monitor.sh logs
```
**Ctrl+C**で終了

#### 3.3 1サイクルだけテスト実行
```bash
./test_one_cycle.sh
```

---

## 🎮 システム管理コマンド

### 起動・停止・再起動
```bash
# 監視を開始
./setup_continuous_monitor.sh start

# 監視を停止
./setup_continuous_monitor.sh stop

# 監視を再起動
./setup_continuous_monitor.sh restart
```

### ログ確認
```bash
# リアルタイムログ（Ctrl+Cで終了）
./setup_continuous_monitor.sh logs

# 最新20行のみ表示
./setup_continuous_monitor.sh status
```

### アンインストール
```bash
./setup_continuous_monitor.sh uninstall
```

---

## 📧 Gmail通知の内容

### 件名
```
[CFD3] 🎯 新規シグナル N件検出！
```

### 本文例
```
🎯 CFD3 自動トレードシグナル検出

⏰ 検出時刻: 2025/11/03 22:30
📊 新規シグナル: 2件
   - STRONG_GO: 1件 ⭐⭐⭐
   - GO: 1件 ⭐⭐

📈 シグナル詳細:
1. ⭐⭐⭐ STRONG_GO - DE40
   エントリー: 19500.00
   TP: 21000.00 | SL: 18750.00
   ロット: 6.0
   リスク額: ¥10,000

2. ⭐⭐ GO - AAPL
   エントリー: 225.00
   TP: 232.00 | SL: 222.00
   ロット: 4.0
   リスク額: ¥7,000

📎 詳細は添付のCSVファイルをご確認ください。

🤖 CFD3 自動監視システム
   7銘柄24時間監視中: JP225, DE40, NASDAQ_MINI, SP500, AAPL, MSFT, GOLD_SPOT
```

### 添付ファイル
- `events_scored_YYYYMMDD_HHMM_internal.csv` - 詳細データ

---

## 🔧 トラブルシューティング

### 問題1: Gmail通知が届かない

#### 原因
- Keychainにパスワードが登録されていない
- Googleアプリパスワードが間違っている

#### 解決方法
```bash
# 再登録
./.venv/bin/python3 -c "import yagmail; yagmail.register('furuta61@gmail.com', '正しいアプリパスワード')"

# テスト送信
./.venv/bin/python3 -c "
import yagmail
yag = yagmail.SMTP('furuta61@gmail.com')
yag.send('furuta61@gmail.com', 'テスト', 'テストメール')
print('送信成功')
"
```

---

### 問題2: サービスが起動しない

#### 原因確認
```bash
# エラーログを確認
cat logs/continuous_monitor.err

# ステータス確認
./setup_continuous_monitor.sh status
```

#### 解決方法
```bash
# 再インストール
./setup_continuous_monitor.sh uninstall
./setup_continuous_monitor.sh install

# 手動起動でエラー確認
./test_one_cycle.sh
```

---

### 問題3: シグナルが検出されない

#### 原因
- マーケットが休場（土日祝）
- 現在のイベントスコアが低い
- events.csvの設定が古い

#### 確認方法
```bash
# 最新のIFD結果を確認
./.venv/bin/python3 show_ifd_latest.py

# マーケットデータを手動更新
./.venv/bin/python3 realtime_ifd_run.py
```

---

## 📊 ログファイルの場所

- **メインログ**: `logs/continuous_monitor.out`
- **エラーログ**: `logs/continuous_monitor.err`
- **通知履歴**: `logs/notification_history.json`
- **IFD結果**: `logs/events_scored_YYYYMMDD_HHMM_internal.csv`

---

## 🚀 推奨運用方法

### 1. 毎朝のチェック
```bash
# 前日の検出数を確認
./setup_continuous_monitor.sh status
```

### 2. 重要イベント前（例: 米雇用統計 22:30）
```bash
# 15分前に手動でも確認
./.venv/bin/python3 realtime_ifd_run.py
./.venv/bin/python3 show_ifd_latest.py
```

### 3. 週次メンテナンス
```bash
# events.csvを更新
./.venv/bin/python3 weekly_events_update.py

# システム再起動
./setup_continuous_monitor.sh restart
```

---

## ⚙️ 高度な設定

### 監視間隔を変更

`continuous_monitor.py`の11行目を編集：
```python
# 15分 = 900秒
MONITOR_INTERVAL = 900

# 例: 10分にする場合
MONITOR_INTERVAL = 600

# 例: 5分にする場合
MONITOR_INTERVAL = 300
```

変更後は再起動：
```bash
./setup_continuous_monitor.sh restart
```

### 通知対象シグナルを変更

`continuous_monitor.py`の14行目を編集：
```python
   # STRONG_GOのみを通知する場合の例
   TARGET_SIGNALS = ['STRONG_GO']
```

---

## 📈 パフォーマンス統計

システムが収集する情報：
- ✅ 監視サイクル回数
- ✅ 検出シグナル数（STRONG_GO / GO別）
- ✅ 送信した通知回数
- ✅ エラー発生回数

確認方法：
```bash
# 通知履歴
cat logs/notification_history.json | python3 -m json.tool

# 1日の統計（ログから集計）
grep "新規シグナル検出" logs/continuous_monitor.out | wc -l
```

---

## 🎓 次のステップ

1. **自動発注システム**との連携
   - MT4/MT5 API統合
   - GMOクリック証券 API統合

2. **リスク管理の強化**
   - 1日の最大損失額制限
   - ポジション数制限

3. **パフォーマンス分析**
   - 勝率・損益率の自動集計
   - 銘柄別パフォーマンス

---

## 📞 サポート

問題が解決しない場合：
1. ログファイルを確認
2. `test_one_cycle.sh`でエラー内容を確認
3. システム要件を確認（Python 3.11, yagmail, pandas等）

---

**🎉 セットアップ完了後、24時間365日の自動監視が始まります！**
