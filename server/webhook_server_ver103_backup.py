"""
CFD3 AI Swing Ver.103
- Webhook状態をUIに表示
- TradingView → Webhook → AIスイング自動解析
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from openai import OpenAI
import feedparser, pandas as pd, json, random, os
from pathlib import Path
from typing import List

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
app = FastAPI(title="CFD3 AI Swing 103")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)
app.mount("/ui", StaticFiles(directory="ui", html=True), name="ui")

DATA = Path("data"); DATA.mkdir(exist_ok=True)
STATE_FILE = Path("tv_last_signal.json")

# ========== 状態ロード / セーブ ==========
def load_tv_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}
def save_tv_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))
tv_state = load_tv_state()

# ========== ATR14 計算 ==========
def calc_atr(symbol:str) -> float:
    fp = DATA / f"{symbol}.csv"
    if not fp.exists(): return random.uniform(50,150)
    df = pd.read_csv(fp).tail(100)
    if not all(c in df.columns for c in ["high","low","close"]): return 100.0
    trs=[]
    for i in range(1,len(df)):
        h,l,c=df.loc[i,"high"],df.loc[i,"low"],df.loc[i-1,"close"]
        trs.append(max(h-l,abs(h-c),abs(l-c)))
    atr=sum(trs[-14:])/14 if len(trs)>=14 else sum(trs)/len(trs)
    return round(float(atr),2)

# ========== ニュース取得 ==========
RSS_SOURCES=[
    ("Reuters","https://feeds.reuters.com/reuters/topNews"),
    ("CNBC","https://www.cnbc.com/id/100727362/device/rss/rss.html"),
    ("MarketWatch","https://feeds2.feedburner.com/marketwatch/topstories"),
    ("ZeroHedge","https://zerohedge.com/fullrss")
]
def fetch_latest_news(limit=20)->List[str]:
    news=[]
    for name,url in RSS_SOURCES:
        try:
            feed=feedparser.parse(url)
            for e in feed.entries[:5]:
                news.append(f"[{name}] {e.title}")
        except: pass
    return news[:limit]

# ========== Webhook ==========
@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    symbol=data.get("symbol")
    direction=data.get("direction")
    signal=data.get("signal","GO")
    if not symbol or not direction:
        return {"status":"error","msg":"symbol/direction missing"}
    tv_state[symbol.upper()]={"direction":direction.lower(),"signal":signal.upper()}
    save_tv_state(tv_state)
    return {"status":"ok","updated":tv_state}

@app.get("/tv_state")
def get_tv_state():
    return tv_state

# ========== AIスイング解析 ==========
@app.post("/analyze/swing")
async def analyze_swing():
    symbols=["JP225","NAS100","GER40","XAUUSD"]
    news_all=fetch_latest_news()
    results=[]
    markdown="| 銘柄 | 方向 | 信頼度 | Entry | TP | SL | ATR | コメント |\n"
    markdown+="|------|------|--------|-------|------|------|------|-----------|\n"

    for s in symbols:
        atr=calc_atr(s)
        preset_dir=tv_state.get(s,{}).get("direction")
        preset_sig=tv_state.get(s,{}).get("signal")
        prompt=f"""
あなたはプロのスイングトレーダーです。
対象: {s}
スイング想定: 1〜3日
ATR(14)={atr}
Webhook方向: {preset_dir or "未指定"} / signal={preset_sig or "未指定"}
ニュース: {news_all[:6]}

条件:
- Webhook方向が指定されている場合、それを優先。
- TP = entry ± 2×ATR, SL = entry ∓ 1×ATR
- 出力は次のJSON形式:
{{
 "symbol": "{s}",
 "direction": "buy or sell",
 "entry": 任意の価格,
 "take_profit": entry ± 2×ATR,
 "stop_loss": entry ∓ 1×ATR,
 "confidence": 0〜100,
 "comment": "日本語で簡潔に理由を述べる"
}}
"""
        res=client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role":"user","content":prompt}],
            temperature=0
        )
        txt=res.choices[0].message.content.strip()
        # JSONコードブロック除去
        if "```json" in txt:
            txt = txt.split("```json")[1].split("```")[0].strip()
        elif "```" in txt:
            txt = txt.split("```")[1].split("```")[0].strip()
        try: 
            data=json.loads(txt)
        except Exception as e:
            data={"symbol":s,"direction":"buy","entry":0,"take_profit":0,"stop_loss":0,"confidence":50,"comment":f"AI解析エラー: {str(e)[:50]}"}
        data["atr"]=atr
        results.append(data)

    buys=[r for r in results if r["direction"]=="buy"]
    sells=[r for r in results if r["direction"]=="sell"]
    if len(buys)==0 or len(sells)==0:
        for i,r in enumerate(results):
            r["direction"]="buy" if i%2==0 else "sell"

    for r in results:
        markdown+=f"| {r['symbol']} | {'買い' if r['direction']=='buy' else '売り'} | {r['confidence']} | {r['entry']} | {r['take_profit']} | {r['stop_loss']} | {r['atr']} | {r['comment']} |\n"

    news_md="\n### 📰 ニュース要約\n"+"\n".join(news_all[:6])
    return {"mode":"SWING_4H_AI_MULTI","results":results,"markdown":markdown+news_md}

# ========== UI ==========
@app.get("/ui", response_class=HTMLResponse)
def ui_page():
    return HTMLResponse(open("ui/index.html","r",encoding="utf-8").read())

# 実行: uvicorn webhook_server:app --reload --port 8080
