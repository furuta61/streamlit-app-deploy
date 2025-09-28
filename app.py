import streamlit as st
from dotenv import load_dotenv
import os
from typing import Optional

# Load env
load_dotenv()

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")


# LLM wrapper function
def generate_answer(prompt: str, role: str) -> str:
    """プロンプトと選択された役割を受け取り、LangChain を使って OpenAI に問い合わせて回答を返す

    引数:
      - prompt: ユーザー入力テキスト
      - role: ラジオボタンで選択された役割 (例: "旅行ガイド" / "栄養士")

    戻り値:
      - LLM の返答テキスト
    """
    # Lazy import to avoid requiring OpenAI/LLM at import time
    try:
        from langchain.chat_models import ChatOpenAI
        from langchain.schema import HumanMessage, SystemMessage

        # System message per role
        if role == "旅行ガイド":
            system_msg = (
                "あなたは経験豊富な旅行ガイドです。旅行のおすすめ、旅程の作成、現地情報の注意点を分かりやすく説明してください。日本語で答えてください。"
            )
        else:
            system_msg = (
                "あなたはプロの栄養士です。バランスの良い食事のアドバイスや栄養計算、健康的な献立の提案を日本語で行ってください。"
            )

        llm = ChatOpenAI(model_name="gpt-4o-mini", temperature=0.2, openai_api_key=OPENAI_API_KEY)
        messages = [SystemMessage(content=system_msg), HumanMessage(content=prompt)]
        resp = llm(messages)
        return resp.content
    except Exception:
        # Let the caller handle/log the exception; re-raise for visibility
        raise


st.set_page_config(page_title="LLM Sample App", page_icon="🤖")
st.title("LLM 搭載サンプルアプリ")
st.write(
    "このアプリは LangChain を使い、OpenAI API にプロンプトを送って応答を表示します。\n\n注意: デプロイ時は Streamlit のシークレットに OPENAI_API_KEY を設定してください。"
)

# Expert roles
role = st.radio("専門家の振る舞いを選択してください", ["旅行ガイド", "栄養士"])

user_input = st.text_area("質問を入力してください", height=150)

if st.button("送信"):
    if not user_input.strip():
        st.error("質問を入力してください")
    elif OPENAI_API_KEY is None:
        st.error("OPENAI_API_KEY が設定されていません。ローカル実行の場合は .env に設定してください。")
    else:
        with st.spinner("LLM を呼び出しています..."):
            try:
                response = generate_answer(user_input, role)
                st.subheader("回答")
                st.write(response)
            except Exception as e:
                st.error(f"LLM 呼び出しでエラーが発生しました: {e}")
