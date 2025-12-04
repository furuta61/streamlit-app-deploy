from openai import OpenAI
import os
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

try:
    res = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role":"user","content":"日経平均の今週の方向性を20字で予測して"}]
    )
    print("✅ GPT通信成功！")
    print("出力内容:", res.choices[0].message.content)
except Exception as e:
    print("❌ GPT通信失敗:", e)
