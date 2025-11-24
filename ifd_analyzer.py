# ifd_analyzer.py
# ---------------------------------------
# 第3層：AIによる IFD 総合分析レイヤー
# Visionで抽出した IFD情報 ＋ ニュース情報（RSS + X）
# を統合してAI評価を行うモジュール
# ---------------------------------------

from openai import OpenAI

# OpenAIクライアント（ここで初期化してOK）
client = OpenAI()


def ai_ifd_analysis(ifd_data, rss_news, x_news):
    """
    IFDデータ（スクショから抽出された内容）と
    RSS＋Xのニュースを使い、
    AIが「GO / STRONG_GO / 安全 / 危険」などを総合判断する関数
    """

    prompt = f"""
あなたはFX/CFD専用のIFD分析アシスタントです。
以下の情報を使って、トレードの安全性と分類（GO/STRONG_GO）を分析してください。

【IFDデータ】
{ifd_data}

【RSSニュース】
{rss_news}

【X速報】
{x_news}

分析ルール（必ず守る）:
1. 銘柄・方向（売り/買い）・エントリー価格の妥当性チェック
2. 損切りは 1口 -6500円（固定）
3. 利確幅から GO / STRONG_GO を分類（利確幅そのものはユーザーが決める）
4. GO = 2〜3口 / STRONG_GO = 最大5口 で整合性チェック
5. ニュースによるリスク（指標前後、地政学、急変動）を判定
6. 最終結果は次のJSON形式で返す:

{{
  "ok": true/false,
  "reason": "問題点・評価コメント",
  "classification": "GO or STRONG_GO or UNKNOWN",
  "news_risk": 0-100,
  "trade_risk": 0-100,
  "final_judgement": "安全 / 注意 / 危険"
}}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )

    return response.choices[0].message.content
