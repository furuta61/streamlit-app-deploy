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

---

この README の手順をリポジトリ内で実行することで、ローカルで Streamlit アプリを立ち上げられるようになります.