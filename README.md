# streamlit-app-deploy

This repository is prepared for deploying a Streamlit app.

## ローカルでのセットアップ（macOS / zsh）

リポジトリのルート（`streamlit-app-deploy`）で仮想環境を作成し、有効化して依存関係をインストールする手順を示します。

1. 仮想環境の作成

```bash
python3 -m venv env
```

2. 仮想環境の有効化（zsh）

```bash
source env/bin/activate
```

3. pip を最新にし、必要なパッケージをインストール

```bash
python -m pip install --upgrade pip
if [ -f requirements.txt ]; then
  python -m pip install -r requirements.txt
else
  python -m pip install streamlit
fi
```

4. Streamlit アプリの起動

```bash
streamlit run app.py
```

注意: macOS に複数の Python バージョンがインストールされている場合、`python3` と `python` の指す先が異なることがあります。上のコマンドは `python3` を使う想定ですが、環境に合わせて `python` を使ってください。

# streamlit-app-deploy / Streamlit LLM App

このリポジトリは、LangChain と OpenAI を使った簡単な Streamlit アプリのサンプルです。教材に沿った下準備（仮想環境、依存関係、.env の扱い）をまとめています。

## 目的
- Streamlit 上でテキスト入力を受け取り、LangChain 経由で LLM（OpenAI）にプロンプトを送り、回答を表示するデモ。

## 前提
- Python 3.11 を推奨します。
- macOS/Windows 両対応（ただし一部ネイティブ依存は OS 固有の準備が必要）。

## クイックスタート（macOS / zsh）

1. リポジトリのルートで仮想環境を作成

```bash
python3 -m venv env
```

2. 仮想環境を有効化

```bash
source env/bin/activate
```

3. pip を最新にして依存関係をインストール

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

4. `.env` を作成して `OPENAI_API_KEY` を設定

```bash
cp .env.example .env
# エディタで .env を開き、OPENAI_API_KEY=sk-... を設定
```

5. アプリを起動

```bash
streamlit run app.py
```

## 教材準拠の注意点
- 教材の `company_inner_search_app` のようなサンプルを使う場合、`data/` フォルダをプロジェクト直下に置きます。
- `requirements_mac.txt` に記載のパッケージ（例: `hnswlib`, `PyMuPDF`, `SudachiPy`）はネイティブビルドが必要なことがあり、macOS では Xcode コマンドラインツールや追加のライブラリが必要です（例: `xcode-select --install`）。
- LangChain のバージョン差に注意してください（教材の依存とローカルアプリの依存が異なる場合があります）。

## デプロイ（Streamlit Community Cloud）
- `.env` はコミットしないでください。Streamlit Cloud を使う場合は、リポジトリの Settings → Secrets に `OPENAI_API_KEY` を設定します。
- Cloud 用の最小依存は `requirements_cloud.txt` を作成してピン留めするとデプロイが安定します（`streamlit==1.41.1` 等）。

## セキュリティ
- 共有フォルダや Google Drive に `.env` を置かないでください。もし誤って共有してしまった場合はキーをローテーションしてください。

## 次にやること（提案）
1. `requirements_cloud.txt`（Streamlit Cloud 用の最小依存）を作成
2. 提出用クリーンスクリプトを追加（`.env`, `.chroma`, `.git` を除外する）
3. 小さなテスト用データセットと読み込みスクリプトを `data/sample/` に追加

必要ならこれらを順に作成します。どれを優先しますか？