# 🚀 クイックスタート：24時間監視システム

## ⚡ 3ステップでセットアップ

### ステップ1: Gmail設定（初回のみ）
```bash
cd '/Users/otomi/Desktop/vs code/CFD3_AutoSystem'
./.venv/bin/python3 -c "import yagmail; yagmail.register('furuta61@gmail.com', 'Googleアプリパスワード16桁')"
```

### ステップ2: システムインストール
```bash
./setup_continuous_monitor.sh install
```

### ステップ3: 動作確認
```bash
./setup_continuous_monitor.sh status
```

---

## 📊 システム概要

**7銘柄を24時間監視し、STRONG_GO/GOシグナルを即座にGmail通知！**

### 監視対象
- JP225, DE40, NASDAQ_MINI, SP500, AAPL, MSFT, GOLD_SPOT

### 特徴
- ⏱️ **15分ごと**に自動チェック（1日96回）
- 📧 **即座にGmail通知**（重複防止機能付き）
- 🔄 **自動再起動**（エラー時も継続）
- 🚀 **macOS起動時に自動起動**

---

## 🎮 よく使うコマンド

```bash
# ログをリアルタイム表示（Ctrl+Cで終了）
./setup_continuous_monitor.sh logs

# ステータス確認
./setup_continuous_monitor.sh status

# 再起動
./setup_continuous_monitor.sh restart

# 1サイクルだけテスト
./test_one_cycle.sh
```

---

## 📧 通知例

```
[CFD3] 🎯 新規シグナル 2件検出！

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
```

---

## 📖 詳細ドキュメント

詳しいセットアップ方法とトラブルシューティングは：
👉 **[docs/CONTINUOUS_MONITOR_SETUP.md](docs/CONTINUOUS_MONITOR_SETUP.md)**

---

## 🔧 トラブルシューティング（よくある問題）

### 通知が届かない場合
```bash
# Gmail設定を再確認
./.venv/bin/python3 -c "
import yagmail
yag = yagmail.SMTP('furuta61@gmail.com')
yag.send('furuta61@gmail.com', 'テスト', 'テストメール')
print('✅ 送信成功')
"
```

### サービスが起動しない場合
```bash
# エラーログ確認
cat logs/continuous_monitor.err

# 手動テスト
./test_one_cycle.sh
```

---

**🎉 これで24時間365日、自動監視が始まります！**
