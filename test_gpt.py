from openai import OpenAI
import os

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

prompt = """
あなたは金融アナリストです。
NASDAQが下落し、金価格が上昇している状況で、
株式市場の投資戦略を簡潔に日本語で説明してください。
"""

res = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role":"user","content":prompt}],
    temperature=0.5
)

print(res.choices[0].message.content)
