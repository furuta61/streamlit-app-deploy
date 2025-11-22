# -*- coding: utf-8 -*-
"""
CFD3 FastAaPI Webhook Server

目的:
- TradingView の Webhook を受信
- RAW JSON をログに保存
- barstate=closed のときだけ CSV へ追記 (DATA_DIR/WEBHOOK_{symbol}_{frame}.csv)
- 条件を満たす場合に IFD ジェネレーター (cfd3_portfolio_update_v2.py) を起動
- Gmail で通知メールを送信
- IFD の JSON を output/ に保存し、簡易サマリを logs/ に追記

必要なライブラリ:
- fastapi, uvicorn, pandas
- smtplib, email
- subprocess, pathlib

実行例 (ローカル):
    uvicorn webhook_server:app --reload --port 8080

"""
from __future__ import annotations

from fastapi import FastAPI, Request, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import os
import json
import base64
from datetime import datetime
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid
import io
import contextlib
import logging
import subprocess
import sys
from pathlib import Path
import pandas as pd
from typing import Optional, Dict, Any, Tuple
from typing import List
from utils_ifd import print_ifd_table, format_ifd_table_text

# OpenAI for AI filter
from openai import OpenAI
openai_client = OpenAI()

# ====== CSV からテクニカル指標を読むヘルパー（GER40 4H 用） ======

# TradingViewシンボル → CSVファイル名 の対応
CSV_FILE_MAP: Dict[str, str] = {
    "GER40": "FOREXCOM_GER40, 240.csv",
    # JP225 / NAS100 / XAUUSD 用はあとで追加できます
    # "JP225": "FOREXCOM_JP225, 240.csv",
    # "NAS100": "FOREXCOM_NAS100, 240.csv",
    # "XAUUSD": "FOREXCOM_XAUUSD, 240.csv",
}


def load_latest_tech(symbol: str) -> Optional[Dict[str, float]]:
    """
    data/FOREXCOM_GER40, 240.csv などから最新バーとテクニカル指標を計算して返す。
    CSVが無い・壊れている場合は None を返す。
    """
    sym = symbol.upper().strip()
    fname = CSV_FILE_MAP.get(sym)
    if not fname:
        logger.warning(f"[tech] CSV_FILE_MAP に {sym} が定義されていません")
        return None

    csv_path = DATA_DIR / fname
    if not csv_path.exists():
        logger.warning(f"[tech] CSV ファイルが見つかりません: {csv_path}")
        return None

    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        logger.warning(f"[tech] CSV 読み込みエラー: {csv_path} / {e}")
        return None

    # time列があればソート
    if "time" in df.columns:
        try:
            df["time"] = pd.to_datetime(df["time"], errors="coerce")
            df = df.dropna(subset=["time"]).sort_values("time")
        except Exception:
            pass

    # 最低限 OHLC が必要
    for col in ["open", "high", "low", "close"]:
        if col not in df.columns:
            logger.warning(f"[tech] CSVに {col} 列がありません: {csv_path}")
            return None

    # 最近 200 本だけ使う（重くなりすぎないように）
    df = df.tail(200).copy()

    close = df["close"]

    # SMA
    df["sma20"] = close.rolling(20).mean()
    df["sma50"] = close.rolling(50).mean()
    df["sma100"] = close.rolling(100).mean()

    # MACD (12,26,9)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    macd_signal = macd.ewm(span=9, adjust=False).mean()

    # RSI(14)
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    # ボリンジャーバンド(20, 2σ)
    m = close.rolling(20).mean()
    std = close.rolling(20).std()
    bb_upper = m + 2 * std
    bb_lower = m - 2 * std

    last = df.index[-1]

    info = {
        "close": float(close.iloc[-1]),
        "sma20": float(df.loc[last, "sma20"]) if not pd.isna(df.loc[last, "sma20"]) else None,
        "sma50": float(df.loc[last, "sma50"]) if not pd.isna(df.loc[last, "sma50"]) else None,
        "sma100": float(df.loc[last, "sma100"]) if not pd.isna(df.loc[last, "sma100"]) else None,
        "macd": float(macd.iloc[-1]),
        "macd_signal": float(macd_signal.iloc[-1]),
        "rsi14": float(rsi.iloc[-1]),
        "bb_upper": float(bb_upper.iloc[-1]) if not pd.isna(bb_upper.iloc[-1]) else None,
        "bb_lower": float(bb_lower.iloc[-1]) if not pd.isna(bb_lower.iloc[-1]) else None,
    }

    # 直近クローズを少しだけ（プロンプト用）
    recent_closes = list(map(float, close.tail(30).tolist()))
    info["recent_closes"] = recent_closes

    return info


# .env 読み込み（インストールされていなければ無視）
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ====== 環境変数・定数 ======
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
GMAIL_TO = os.getenv("GMAIL_TO", "")

# CSV/ログ/出力ディレクトリ
REPO_ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(REPO_ROOT / "data")))
LOGS_DIR = REPO_ROOT / "logs"
OUTPUT_DIR = REPO_ROOT / "output"

# ログファイル
RAW_LOG = LOGS_DIR / "tradingview_raw.log"
SMTP_LOG = LOGS_DIR / "notify_smtp.log"

# IFD スクリプト (既存)
IFD_SCRIPT = REPO_ROOT / "cfd3_portfolio_update_v2.py"

# ロガー
logger = logging.getLogger("webhook_server")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="CFD3 Webhook Server")


# ====== AI チャートフィルター（CSV + テクニカル指標付き） ======
def ai_filter_signal(symbol: str, timeframe: str, direction: str, price: float, signal: str) -> Dict[str, Any]:
    """
    CSVからテクニカル指標を読み込み、GPT-4o-miniでシグナルの妥当性を判定。
    
    Returns:
        {
            "ok": bool,    # True=取引OK, False=取引NG
            "score": int,  # 0-100の確率
            "reason": str  # 理由
        }
    """
    sym = symbol.upper().strip()
    tf = timeframe.upper().strip()
    dir_l = direction.lower().strip()
    sig = signal.upper().strip()

    tech = load_latest_tech(sym)

    # テクニカル情報をテキスト化
    if tech:
        tech_text = f"""
[テクニカル情報 (最新バー)]
- close: {tech.get('close')}
- SMA20: {tech.get('sma20')}
- SMA50: {tech.get('sma50')}
- SMA100: {tech.get('sma100')}
- MACD: {tech.get('macd')}
- MACDシグナル: {tech.get('macd_signal')}
- RSI14: {tech.get('rsi14')}
- BB上限: {tech.get('bb_upper')}
- BB下限: {tech.get('bb_lower')}
- 直近クローズ(約30本): {tech.get('recent_closes')}
"""
    else:
        tech_text = "\n[テクニカル情報] CSV読み込みに失敗したため、数値はなしで評価してください。"

    prompt = f"""
あなたはプロの裁量トレーダー兼システムトレーダーです。
以下のCFDシグナルの妥当性を、チャートの方向性ベースで「適度に厳しめ」に評価してください。

■ 銘柄: {sym}
■ 時間足: {tf}
■ 方向: {dir_l}
■ シグナル: {sig}
■ 現在価格: {price}

{tech_text}

=== 評価方針 ===
- トレンド方向: SMA20 / SMA50 / SMA100 の並びと、価格がどの位置にあるかを最重要視。
- MACD: ゼロラインとの位置、シグナルとの位置関係、勢いを確認。
- RSI14: 30〜70 を基準に、トレンド方向と逆行していないか確認。
- ボリンジャーバンド: バンドの上限/下限での逆張りは慎重に。
- 直近クローズの形（トレンド or レンジ）も参考にし、ノイズだけのシグナルは避ける。

=== 判定ルール ===
- 「トレンド方向に素直に乗っているシグナル」のみ高評価。
- 強い逆張り・レンジのど真ん中・指標がバラバラな場合はスコアを下げる。
- score は 0〜100 の整数。
    - score < 35 → ok = false（エントリーすべきでない）
    - score ≥ 35 → ok = true（エントリー許可）

=== 出力形式（JSONのみ, 余計なテキスト禁止） ===
{{
  "ok": true or false,
  "score": 数値,
  "reason": "日本語で、簡潔に理由を1〜2行で説明"
}}
"""

    try:
        res = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}]
        )
        content = res.choices[0].message.content.strip()

        # ```json ... ``` で返ってきた場合のガード
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1]).strip()

        data = json.loads(content)

        # 最低限のキーが無ければフォールバック
        if not isinstance(data, dict) or "ok" not in data or "score" not in data:
            raise ValueError("unexpected AI filter response")

        return data

    except Exception as e:
        logger.error(f"AI filter error: {e}")
        # エラー時は安全のため「やや厳しめOK」にする
        return {"ok": True, "score": 50, "reason": f"AI判定エラーのためデフォルト許可: {e}"}


# ====== スクショ画像AI解析 ======
def analyze_image_with_ai(image_bytes: bytes, symbol_hint: str | None = None) -> Dict[str, Any]:
    """
    GMOのスクショ画像から、AIに以下を推定させる:
      - symbol        : 銘柄名（推定できなければ symbol_hint を使う）
      - direction     : buy / sell
      - entry         : 推奨エントリー価格
      - tp1, tp2, sl  : 目安レベル
      - confidence    : 0-100 の自信度
      - comment       : 日本語コメント
    """
    b64 = base64.b64encode(image_bytes).decode("utf-8")

    prompt = f"""
あなたはプロのCFDトレーダー兼テクニカルアナリストです。
添付のトレード画面（GMO CFD 等）のスクリーンショットを見て、
エントリーとIFD候補を提案してください。

要件:

1. できる範囲で銘柄(symbol)を推定してください。
   - 画像から明確に分からない場合は、symbol は "UNKNOWN" としてください。
   - 引数のヒント symbol_hint が渡されていた場合は、それを優先して使っても構いません。

2. 次の項目を決めてください:
   - direction : "buy" か "sell"
   - entry     : 現在レート付近の、妥当なエントリー価格
   - tp1       : 利確1の目安
   - tp2       : 利確2の目安（中〜長め）
   - sl        : 損切りの目安
   - confidence: 0〜100 の整数で、自分の提案の自信度
   - comment   : なぜその方向と水準にしたか、日本語で1〜3行

3. 注意点:
   - スキャルではなく、数十分〜数時間を想定したデイトレ〜短期スイングレベルのIFDを提案してください。
   - 明らかに方向感がないレンジの場合は、自信度を下げて構いません。

出力は必ず次のJSON「だけ」を返してください。前後に説明文は書かないでください:

{{
  "symbol": "<銘柄 or UNKNOWN>",
  "direction": "buy or sell",
  "entry": 価格の数値,
  "tp1": 価格の数値,
  "tp2": 価格の数値,
  "sl": 価格の数値,
  "confidence": 0〜100 の整数,
  "comment": "日本語コメント"
}}
"""

    try:
        res = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{b64}"
                            },
                        },
                    ],
                }
            ],
        )
        content = res.choices[0].message.content.strip()

        # ```json ... ``` で返ってきた場合に備えて除去
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1]).strip()

        data = json.loads(content)

        # symbol_hint があれば補完
        if symbol_hint and (not data.get("symbol") or data.get("symbol") == "UNKNOWN"):
            data["symbol"] = symbol_hint

        return data
    except Exception as e:
        logger.exception(f"analyze_image_with_ai error: {e}")
        # 失敗時は最低限のダミーを返す
        return {
            "symbol": symbol_hint or "UNKNOWN",
            "direction": "buy",
            "entry": 0,
            "tp1": 0,
            "tp2": 0,
            "sl": 0,
            "confidence": 0,
            "comment": f"AI解析に失敗しました: {e}",
        }


# ====== Pydantic Models ======
class WebhookPayload(BaseModel):
    symbol: Optional[str] = None
    timeframe: Optional[str] = None
    barstate: Optional[str] = None
    text: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    time: Optional[str] = None
    is_realtime: Optional[bool] = None
    # OHLC (平文または data 内にも入ることあり)
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None


class IfdRunRequest(BaseModel):
    tf: Optional[str] = "4h"
    symbols: Optional[str] = None  # カンマ区切り
    single: Optional[bool] = True
    expiry_hours: Optional[int] = 0
    trade_mode: Optional[str] = None


class Manual30Request(BaseModel):
    symbol: str
    direction: str  # buy/sell
    entry: float
    signal: str  # GO / STRONG_GO
    save: Optional[bool] = True


# ====== ユーティリティ ======

def timeframe_to_frame(tf: str | None) -> str:
    """TradingView 由来の timeframe を '30'|'60'|'240' のいずれかに正規化。"""
    t = (tf or "").lower()
    if t in ("30", "30m"):  # 30分
        return "30"
    if t in ("60", "60m", "1h", "1hour", "1-hour"):  # 1時間
        return "60"
    if t in ("240", "4h", "4hour", "4-hour"):  # 4時間
        return "240"
    # 既定: 60
    return "60"


def parse_time_to_utc(tval: Any) -> pd.Timestamp:
    """ISO/epoch(ms|s) を UTC Timestamp に変換。異常時は now(UTC)。"""
    if tval is None:
        return pd.Timestamp.utcnow().tz_localize("UTC")
    # 数値っぽい場合は epoch を推定
    try:
        if isinstance(tval, (int, float)) or (isinstance(tval, str) and tval.strip().isdigit()):
            v = float(tval)
            # 大きさで秒/ミリ秒を判定
            if v > 1e12:  # ms
                return pd.to_datetime(v, unit="ms", utc=True)
            if v > 1e9:  # s
                return pd.to_datetime(v, unit="s", utc=True)
    except Exception:
        pass
    # 文字列のときは pandas に任せる
    try:
        ts = pd.to_datetime(tval, utc=True)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return ts
    except Exception:
        return pd.Timestamp.utcnow().tz_localize("UTC")


def is_bar_closed(payload: WebhookPayload) -> bool:
    # 明示 barstate
    try:
        if (payload.barstate or "").lower() in ("closed", "bar_closed", "bar_close", "close"):
            return True
    except Exception:
        pass
    # data 内
    try:
        d = payload.data or {}
        bs = str(d.get("barstate") or d.get("bar_state") or "").lower()
        if bs in ("closed", "bar_closed", "bar_close", "close"):
            return True
    except Exception:
        pass
    # テキストヒューリスティック
    try:
        txt = (payload.text or "").lower()
        if any(k in txt for k in ["bar close", "bar_closed", "closed bar", "closed"]):
            return True
    except Exception:
        pass
    return False


def send_email(subject: str, body: str, to_addrs: str):
    """Gmail SMTP(SSL:465) でプレーンテキスト送信。"""
    smtp_user = GMAIL_USER
    smtp_pass = GMAIL_APP_PASSWORD
    recipients = to_addrs or GMAIL_TO

    if not smtp_user or not smtp_pass or not recipients:
        raise RuntimeError("メール設定が不完全です (.env の GMAIL_* を確認)。")

    rcpts = [r.strip() for r in recipients.split(",") if r.strip()]

    msg = EmailMessage()
    msg["From"] = f"CFD3 Alerts <{smtp_user}>"
    msg["To"] = ", ".join(rcpts)
    msg["Subject"] = subject
    msg["Reply-To"] = smtp_user
    try:
        msg["Message-ID"] = make_msgid()
    except Exception:
        pass
    msg.set_content(body)

    smtp_host = "smtp.gmail.com"
    smtp_port = 465

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    debug_out = ""
    with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20) as smtp:
        smtp.set_debuglevel(1)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            smtp.login(smtp_user, smtp_pass)
            smtp.send_message(msg, from_addr=smtp_user, to_addrs=rcpts)
        debug_out = buf.getvalue()

    # SMTP デバッグをファイルにも残す
    try:
        with open(SMTP_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.utcnow().isoformat(),
                "to": rcpts,
                "subject": subject,
                "status": "sent",
            }, ensure_ascii=False) + "\n")
            if debug_out:
                tail = debug_out.splitlines()[-20:]
                f.write("\n".join(tail) + "\n\n")
    except Exception:
        pass


def append_csv(symbol: str, frame: str, payload: WebhookPayload) -> Path:
    """DATA_DIR/WEBHOOK_{symbol}_{frame}.csv に 1 レコード追記（重複は time で排除）。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fn = DATA_DIR / f"WEBHOOK_{symbol}_{frame}.csv"

    # OHLC の抽出（payload 平文優先→data 辞書）
    ohlc = {}
    if payload.open is not None:
        ohlc = {
            "open": payload.open,
            "high": payload.high,
            "low": payload.low,
            "close": payload.close,
        }
    elif payload.data:
        d = payload.data
        def pick(dd: Dict[str, Any], keys):
            for k in keys:
                if k in dd:
                    return dd.get(k)
            return None
        ohlc = {
            "open": pick(d, ("o", "open")),
            "high": pick(d, ("h", "high")),
            "low": pick(d, ("l", "low")),
            "close": pick(d, ("c", "close")),
        }

    # time の決定
    tval = payload.time or ((payload.data or {}).get("time"))
    ts = parse_time_to_utc(tval)

    row = pd.DataFrame([{
        "time": ts,
        "open": float(ohlc.get("open", ohlc.get("close", 0.0)) or 0.0),
        "high": float(ohlc.get("high", ohlc.get("close", 0.0)) or 0.0),
        "low": float(ohlc.get("low", ohlc.get("close", 0.0)) or 0.0),
        "close": float(ohlc.get("close", 0.0) or 0.0),
    }])

    if fn.exists():
        try:
            old = pd.read_csv(fn, parse_dates=[0])
            if old.columns[0].lower() != "time":
                old.columns = ["time"] + list(old.columns[1:])
            df = pd.concat([old, row], ignore_index=True)
        except Exception:
            df = row
    else:
        df = row

    df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
    df = df.dropna(subset=["time"]).drop_duplicates(subset=["time"], keep="last").sort_values("time").reset_index(drop=True)
    df.to_csv(fn, index=False)
    logger.info("wrote csv: %s (rows=%d)", str(fn), len(df))
    return fn


def run_ifd(symbol: str, tf: str = "4h") -> Tuple[int, str, str, Optional[dict]]:
    """IFD ジェネレーターを実行して (returncode, stdout, stderr, parsed_json) を返す。"""
    if not IFD_SCRIPT.exists():
        return (127, "", f"not found: {IFD_SCRIPT}", None)

    args = [
        sys.executable,
        str(IFD_SCRIPT),
        "--data", str(DATA_DIR),
        "--tf", str(tf),
        "--single",
        "--only", symbol,
    ]
    logger.info("running IFD: %s", " ".join(args))
    proc = subprocess.run(args, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=180)

    out, err = proc.stdout or "", proc.stderr or ""
    logger.info("IFD stdout (head): %s", out[:1200])
    logger.info("IFD stderr (head): %s", err[:1200])

    parsed = None
    s = out.strip()
    if s:
        try:
            parsed = json.loads(s)
        except Exception:
            first = s.find("{")
            last = s.rfind("}")
            if first != -1 and last != -1 and last > first:
                try:
                    parsed = json.loads(s[first:last+1])
                except Exception:
                    parsed = None

    # JSON を保存 + サマリ追記
    if parsed:
        try:
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            run_id = parsed.get("run_id") or datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            out_fp = OUTPUT_DIR / f"ifd_{run_id}.json"
            with open(out_fp, "w", encoding="utf-8") as f:
                json.dump(parsed, f, ensure_ascii=False, indent=2)
            logger.info("Saved IFD JSON to %s", str(out_fp))

            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            summary_fp = LOGS_DIR / f"ifd_summary_{datetime.utcnow().strftime('%Y%m%d')}.csv"
            rows = []
            for order in parsed.get("orders", []):
                inst = order.get("instrument", "")
                decision = order.get("decision", "")
                lots = order.get("lots", "")
                entry = ""
                try:
                    entry = str(order.get("entry_order", {}).get("price", ""))
                except Exception:
                    pass
                tp1 = tp2 = sl = ""
                legs = order.get("ifd_legs") or []
                if legs and isinstance(legs, list):
                    try:
                        oco = legs[0].get("oco", {})
                        tp = oco.get("take_profit") or {}
                        slv = oco.get("stop_loss") or {}
                        tp1 = str(tp.get("price", "")) if isinstance(tp, dict) else ""
                        sl = str(slv.get("price", "")) if isinstance(slv, dict) else ""
                    except Exception:
                        pass
                rows.append((run_id, datetime.utcnow().isoformat(), inst, decision, entry, sl, tp1, tp2, lots))

            import csv
            write_header = not summary_fp.exists()
            with open(summary_fp, "a", newline="", encoding="utf-8") as cf:
                writer = csv.writer(cf)
                if write_header:
                    writer.writerow(["run_id","ts","instrument","decision","entry","SL","TP1","TP2","lots"])
                for r in rows:
                    writer.writerow(r)
            logger.info("Appended IFD summary to %s", str(summary_fp))
        except Exception:
            logger.exception("Failed to persist IFD artifacts")

    return (proc.returncode, out, err, parsed)


# ====== 4H 手動IFDユーティリティ ======
# 既存 cfd3_portfolio_update_v2.py の距離設計に準拠（TPは per_lot_jpy / point_value、TP2 は 1.5倍、SL は TP距離の1/3）
DECIMALS_MAP: Dict[str, int] = {
    "JP225": 0,
    "NAS100": 1,
    "GER40": 0,
    "XAUUSD": 2,
}

POINT_VALUE_MAP: Dict[str, float] = {
    "JP225": 100.0,
    "NAS100": 20.0,
    "GER40": 80.0,
    "XAUUSD": 150.0,
}


def _round_price(symbol: str, price: float) -> float:
    d = DECIMALS_MAP.get(symbol.upper(), 1)
    return round(float(price), d)


def generate_4h_ifd(symbol: str, direction: str, entry_price: float, signal: str) -> dict:
    sym = symbol.upper().strip()
    side = direction.lower().strip()
    sig = signal.upper().strip()

    if sig not in ("GO", "STRONG_GO"):
        raise ValueError("signal は GO または STRONG_GO のみ")
    if side not in ("buy", "sell"):
        raise ValueError("direction は buy / sell のみ")

    # 4H 既定: STRONG_GO=2000円/口, GO=800円/口、ロット 6 / 4
    per_lot = 2000.0 if sig == "STRONG_GO" else 800.0
    lots = 6 if sig == "STRONG_GO" else 4

    pv = float(POINT_VALUE_MAP.get(sym, 1.0))
    try:
        tp_distance = float(per_lot) / pv
    except Exception:
        tp_distance = float(per_lot)
    tp2_distance = tp_distance * 1.5
    sl_distance = tp_distance / 3.0

    e = float(entry_price)
    if side == "buy":
        tp1 = e + tp_distance
        tp2 = e + tp2_distance
        sl = e - sl_distance
    else:
        tp1 = e - tp_distance
        tp2 = e - tp2_distance
        sl = e + sl_distance

    # 丸め
    entry_r = _round_price(sym, e)
    tp1_r = _round_price(sym, tp1)
    tp2_r = _round_price(sym, tp2)
    sl_r = _round_price(sym, sl)

    run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    ifd = {
        "run_id": run_id,
        "trade_mode": "SYSTEM_4H",
        "orders": [
            {
                "instrument": sym,
                "direction": side,
                "decision": sig,
                "lots": lots,
                "entry_order": {"type": "limit", "price": entry_r},
                "ifd_legs": [
                    {
                        "name": "IFD-1",
                        "oco": {
                            "take_profit": {"price": tp1_r},
                            "stop_loss": {"price": sl_r},
                        },
                    },
                    {
                        "name": "IFD-2",
                        "oco": {
                            "take_profit": {"price": tp2_r},
                            "stop_loss": {"price": sl_r},
                        },
                    },
                ],
            }
        ],
        # ★ 4HのTP2をトップレベルにも明示
        "tp2_price": tp2_r,
    }
    return ifd


def save_ifd_json(obj: dict, prefix: str = "ifd_4h_") -> str:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    run_id = obj.get("run_id") or datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_fp = OUTPUT_DIR / f"{prefix}{run_id}.json"
    with open(out_fp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

    # 簡易サマリ
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        summary_fp = LOGS_DIR / f"ifd_summary_{datetime.utcnow().strftime('%Y%m%d')}.csv"
        import csv
        write_header = not summary_fp.exists()
        rows: List[List[str]] = []
        for order in obj.get("orders", []):
            inst = order.get("instrument", "")
            decision = order.get("decision", "")
            lots = order.get("lots", "")
            entry = str(order.get("entry_order", {}).get("price", ""))
            tp1 = tp2 = sl = ""
            legs = order.get("ifd_legs") or []
            if legs:
                oco0 = legs[0].get("oco", {})
                tp1 = str((oco0.get("take_profit") or {}).get("price", ""))
                sl = str((oco0.get("stop_loss") or {}).get("price", ""))
                if len(legs) > 1:
                    oco1 = legs[1].get("oco", {})
                    tp2 = str((oco1.get("take_profit") or {}).get("price", ""))
            rows.append([obj.get("run_id"), datetime.utcnow().isoformat(), inst, decision, entry, sl, tp1, tp2, str(lots)])

        with open(summary_fp, "a", newline="", encoding="utf-8") as cf:
            writer = csv.writer(cf)
            if write_header:
                writer.writerow(["run_id","ts","instrument","decision","entry","SL","TP1","TP2","lots"])
            for r in rows:
                writer.writerow(r)
    except Exception:
        logger.exception("failed to append 4H ifd summary")

    return str(out_fp)


def send_ifd_email(ifd_json: dict):
    """4H IFD 生成通知メール（表形式付き）。"""
    try:
        body = "4時間IFDが生成されました。\n\n"
        body += format_ifd_table_text(ifd_json)
        body += "\n(JSONデータは添付またはログを参照)\n"
        send_email(subject="【4H IFD】注文生成", body=body, to_addrs=GMAIL_TO)
    except Exception:
        logger.exception("email send failed (4H ifd)")


# ====== Endpoints ======
@app.post("/analyze/image")
async def analyze_image(symbol: Optional[str] = None, file: UploadFile = File(...)):
    """
    GMO 等のスクショ画像を受け取り、AIで方向・価格帯を解析し、
    ついでに 30分手動IFD形式のJSONも生成して返すエンドポイント。
    """
    try:
        img_bytes = await file.read()
        if not img_bytes:
            raise HTTPException(status_code=400, detail="画像データが空です")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"画像の読み込みに失敗しました: {e}")

    # 画像からAIで解析
    analysis = analyze_image_with_ai(img_bytes, symbol_hint=symbol)

    # manual30_ifd を使って IFD JSON を組み立てる（confidence で GO / STRONG_GO を分ける）
    ifd_json = None
    error_msg = None
    try:
        from manual30_ifd import generate_ifd as generate_manual30_ifd

        sym = (analysis.get("symbol") or symbol or "UNKNOWN").upper()
        direction = str(analysis.get("direction") or "buy").lower()
        entry = float(analysis.get("entry") or 0)

        # 自信度で GO / STRONG_GO を切り替え（70以上なら STRONG_GO）
        conf = int(analysis.get("confidence") or 0)
        signal = "STRONG_GO" if conf >= 70 else "GO"

        ifd_json = generate_manual30_ifd(sym, direction, entry, signal)
    except Exception as e:
        logger.exception("failed to generate manual30 IFD from image analysis")
        error_msg = f"IFD生成に失敗しました: {e}"

    return {
        "status": "ok",
        "analysis": analysis,
        "ifd": ifd_json,
        "ifd_error": error_msg,
    }


@app.post("/webhook")
async def webhook_handler(request: Request):
    """4H アラート → 自動IFD生成ハンドラ（AIフィルター付き）。
    TradingView 側から以下のJSONが送られる想定:
      {
        "timeframe":"4H", "symbol":"GER40", "direction":"sell",
        "price":23762, "signal":"STRONG_GO"
      }
    """
    try:
        data = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid json: {e}")

    if str(data.get("timeframe", "")).upper() == "4H":
        try:
            symbol = str(data["symbol"]).upper()
            direction = str(data["direction"]).lower()
            price = float(data["price"])
            signal = str(data["signal"]).upper()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"missing or invalid fields: {e}")

        # ★ AIフィルター判定 ★
        logger.info(f"AI filter check: {symbol} {direction} @ {price}")
        filter_result = ai_filter_signal(symbol, "4H", direction, price, signal)
        
        if not filter_result["ok"]:
            logger.warning("=== AI フィルターで拒否されました ===")
            logger.warning(f"Score: {filter_result['score']}")
            logger.warning(f"Reason: {filter_result['reason']}")
            return {
                "status": "filtered",
                "detail": filter_result,
                "message": "AIフィルターによりエントリーが拒否されました"
            }
        
        logger.info(f"AI filter passed: Score={filter_result['score']}, Reason={filter_result['reason']}")

        # IFD生成（このモジュール内の generate_4h_ifd を利用）
        try:
            ifd_json = generate_4h_ifd(symbol, direction, price, signal)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"generate_4h_ifd failed: {e}")

        # ▼ 表形式でターミナル表示
        try:
            print_ifd_table(ifd_json)
        except Exception:
            logger.exception("failed to print table for 4H IFD")

        # 保存
        saved = None
        try:
            saved = save_ifd_json(ifd_json, symbol)
        except Exception:
            logger.exception("failed to save 4H IFD json")

        # メール
        try:
            send_ifd_email(ifd_json)
        except Exception:
            logger.exception("failed to send 4H IFD email")

        return {
            "status": "4H IFD generated",
            "ifd": ifd_json,
            "saved": saved,
        }

    return {"status": "ignored"}


@app.post("/webhook/test")
async def webhook_test(payload: WebhookPayload):
    return {"received": payload.dict(), "data_dir": str(DATA_DIR)}


@app.post("/ifd/run")
async def ifd_run(req: IfdRunRequest):
    if not IFD_SCRIPT.exists():
        raise HTTPException(status_code=404, detail=f"IFD script not found: {IFD_SCRIPT}")

    args = [
        sys.executable, str(IFD_SCRIPT),
        "--data", str(DATA_DIR),
    ]
    if req.tf:
        args += ["--tf", str(req.tf)]
    if req.single:
        args.append("--single")
    if req.expiry_hours is not None and int(req.expiry_hours) > 0:
        args += ["--expiry-hours", str(int(req.expiry_hours))]
    if req.trade_mode:
        args += ["--trade-mode", str(req.trade_mode)]
    if req.symbols:
        args += ["--only", str(req.symbols)]

    try:
        proc = subprocess.run(args, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="IFD run timed out")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"IFD run failed: {e}")

    out = proc.stdout or ""
    s = out.strip()
    parsed = None
    if s:
        try:
            parsed = json.loads(s)
        except Exception:
            first = s.find("{")
            last = s.rfind("}")
            if first != -1 and last != -1 and last > first:
                try:
                    parsed = json.loads(s[first:last+1])
                except Exception:
                    parsed = None

    return {
        "args": args,
        "returncode": proc.returncode,
        "stdout": out[:4000],
        "stderr": (proc.stderr or '')[:4000],
        "parsed": bool(parsed is not None),
        "ifd_json": parsed,
    }


@app.post("/ifd/manual30")
async def ifd_manual30(req: Manual30Request):
    """30分 手動IFDをAPI経由で生成。JSON保存と簡易サマリ追記も行う。"""
    try:
        from manual30_ifd import generate_ifd as generate_manual30_ifd
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"manual30_ifd import failed: {e}")

    try:
        obj = generate_manual30_ifd(req.symbol, req.direction, float(req.entry), req.signal)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"generate_ifd error: {e}")

    saved_path = None
    try:
        if req.save:
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            run_id = obj.get("run_id") or datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            out_fp = OUTPUT_DIR / f"ifd_manual30_{run_id}.json"
            with open(out_fp, "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False, indent=2)
            saved_path = str(out_fp)

            # 簡易サマリ (1本目のみ)
            try:
                LOGS_DIR.mkdir(parents=True, exist_ok=True)
                summary_fp = LOGS_DIR / f"ifd_summary_{datetime.utcnow().strftime('%Y%m%d')}.csv"
                import csv
                write_header = not summary_fp.exists()
                rows: List[List[str]] = []
                for order in obj.get("orders", []):
                    inst = order.get("instrument", "")
                    decision = order.get("decision", "")
                    lots = order.get("lots", "")
                    entry = ""
                    try:
                        entry = str(order.get("entry_order", {}).get("price", ""))
                    except Exception:
                        pass
                    tp = sl = ""
                    try:
                        legs = order.get("ifd_legs") or []
                        if legs:
                            oco = legs[0].get("oco", {})
                            tp = str((oco.get("take_profit") or {}).get("price", ""))
                            sl = str((oco.get("stop_loss") or {}).get("price", ""))
                    except Exception:
                        pass
                    rows.append([obj.get("run_id"), datetime.utcnow().isoformat(), inst, decision, entry, sl, tp, "", str(lots)])

                with open(summary_fp, "a", newline="", encoding="utf-8") as cf:
                    writer = csv.writer(cf)
                    if write_header:
                        writer.writerow(["run_id","ts","instrument","decision","entry","SL","TP1","TP2","lots"])
                    for r in rows:
                        writer.writerow(r)
            except Exception:
                logger.exception("failed to append manual30 summary")
    except Exception:
        logger.exception("manual30 ifd persistence failed")

    return {
        "status": "ok",
        "saved": saved_path,
        "ifd_json": obj,
    }


@app.post("/webhook/v2")
async def webhook_handler(request: Request):
    """シンプルな 4H Webhook ハンドラ。
    期待するJSON例:
      {
        "timeframe": "4H",
        "symbol": "GER40",
        "direction": "sell",
        "price": 23762,
        "signal": "STRONG_GO"
      }
    """
    try:
        data = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid json: {e}")

    tfv = str(data.get("timeframe", "")).upper()
    if tfv == "4H":
        try:
            symbol = str(data["symbol"]).upper()
            direction = str(data["direction"]).lower()
            price = float(data["price"])
            signal = str(data["signal"]).upper()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"missing or invalid fields: {e}")

        # 4H IFD生成
        try:
            ifd_json = generate_4h_ifd(symbol, direction, price, signal)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"generate_4h_ifd failed: {e}")

        # 保存
        try:
            saved = save_ifd_json(ifd_json, prefix="ifd_4h_")
        except Exception:
            logger.exception("failed to save 4H IFD json")
            saved = None

        # メール送信
        try:
            send_ifd_email(ifd_json)
        except Exception:
            logger.exception("failed to send 4H IFD email")

        return {"status": "4H IFD generated", "ifd": ifd_json, "saved": saved}

    return {"status": "ignored"}


# ====== 起動メモ ======
# ローカル起動例:
#   uvicorn webhook_server:app --reload --port 8080
