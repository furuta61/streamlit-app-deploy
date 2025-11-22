"""
app/datafeed/gmo_realtime.py

GMOクリック CFD のレートを取得する汎用クライアント（WebSocket / HTTP 兼用）。

今回のポイント:
- HTTP の getRanking?rankingType=1&... の JSON
  { status, message, datetime, result: { rankingList: [ {cfdProductCode, ...}, ... ] } }
  をパースして JP225 / NQ100 / GER40 / XAUUSD などのレートに変換する。
- 銘柄コード(cfdProductCode) → 内部シンボル(JP225など) は GMO_SYMBOL_MAP でマッピング。
"""

from __future__ import annotations

import os
import ssl
import json
import time
import threading
from typing import Dict, Optional, Literal, Any, Iterable

import websocket  # pip install websocket-client
import requests   # pip install requests


Mode = Literal["websocket", "http"]


# ─────────────────────────────
# GMO 固有の設定：ここだけ埋めれば OK
# ─────────────────────────────

# getRanking の result.rankingList[i].cfdProductCode → 内部シンボル の対応
# 例: {"100350800000": "JP225", "10035xxxxx": "NQ100", ...}
# 実際の cfdProductCode は Preview の rankingList[] の中を見てメモしてください。
GMO_SYMBOL_MAP: Dict[str, str] = {
    # TODO: 実際のコードを埋める
    # "100350800000": "JP225",
    # "10035xxxxx01": "NQ100",
    # "10035xxxxx02": "GER40",
    # "10035xxxxx03": "XAUUSD",
}

# rankingList の各要素から「価格」を拾う候補キー
PRICE_KEY_CANDIDATES = [
    "price", "lastPrice", "latestPrice", "currentPrice",
    "cfdPrice", "nowPrice", "value",
]

# 汎用パーサ用のキー候補（WSなどで直接 symbol/bid/ask が来る場合用）
SYMBOL_KEY_CANDIDATES = ["symbol", "Symbol", "issueCode", "code"]
BID_KEY_CANDIDATES    = ["bid", "Bid", "sell", "sellPrice", "bidPrice"]
ASK_KEY_CANDIDATES    = ["ask", "Ask", "buy", "buyPrice", "askPrice"]
TIME_KEY_CANDIDATES   = ["timestamp", "time", "quoteTime", "serverTime", "datetime"]


def _find_first_key(d: Dict[str, Any], candidates: list[str]) -> Optional[str]:
    """候補リストのうち、dict に存在する最初のキー名を返す。無ければ None。"""
    if not isinstance(d, dict):
        return None
    lower_map = {k.lower(): k for k in d.keys()}
    for c in candidates:
        if c in d:
            return c
        if c.lower() in lower_map:
            return lower_map[c.lower()]
    return None


def _extract_tick_generic(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    汎用 JSON から tick を抽出（symbol/bid/ask/timestamp が素直に入っている場合用）。
    """
    if not isinstance(msg, dict):
        return None

    k_sym = _find_first_key(msg, SYMBOL_KEY_CANDIDATES)
    k_bid = _find_first_key(msg, BID_KEY_CANDIDATES)
    k_ask = _find_first_key(msg, ASK_KEY_CANDIDATES)
    k_tim = _find_first_key(msg, TIME_KEY_CANDIDATES)

    if not (k_sym and k_bid):
        return None

    try:
        symbol = str(msg[k_sym])
        bid = float(msg[k_bid])
        ask = float(msg[k_ask]) if k_ask and msg.get(k_ask) is not None else bid
    except Exception:
        return None

    ts = None
    if k_tim and msg.get(k_tim) is not None:
        ts = str(msg[k_tim])

    return {
        "symbol": symbol,
        "bid": bid,
        "ask": ask,
        "timestamp": ts,
        "raw": msg,
    }


def _parse_gmo_ranking(data: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    """
    GMO の getRanking JSON を JP225 / NQ100 / GER40 / XAUUSD などの tick に変換する。

    期待する構造:
    {
      "status": "0",
      "message": "",
      "datetime": "20251115024428",
      "result": {
        "rankingList": [
          {
            "cfdProductCode": "100350800000",
            ... 価格っぽいフィールド ...
          },
          ...
        ]
      }
    }
    """
    if not isinstance(data, dict):
        return []

    result = data.get("result")
    if not isinstance(result, dict):
        return []

    ranking_list = result.get("rankingList")
    if not isinstance(ranking_list, list):
        return []

    global_ts = None
    # datetime が "YYYYMMDDhhmmss" 形式っぽいので、そのまま文字列として扱う
    if data.get("datetime"):
        global_ts = str(data["datetime"])

    ticks: list[Dict[str, Any]] = []
    for item in ranking_list:
        if not isinstance(item, dict):
            continue

        code = str(
            item.get("cfdProductCode")
            or item.get("issueCode")
            or item.get("symbol")
            or ""
        )
        if not code:
            continue

        symbol = GMO_SYMBOL_MAP.get(code)
        if not symbol:
            # マッピングしていない銘柄はスキップ（必要ならここで print しても良い）
            continue

        price_key = _find_first_key(item, PRICE_KEY_CANDIDATES)
        if not price_key or item.get(price_key) is None:
            continue

        try:
            price = float(item[price_key])
        except Exception:
            continue

        ts = global_ts
        # item 側に時間っぽいキーがあればそれを優先
        k_tim = _find_first_key(item, TIME_KEY_CANDIDATES)
        if k_tim and item.get(k_tim) is not None:
            ts = str(item[k_tim])

        ticks.append(
            {
                "symbol": symbol,
                "bid": price,
                "ask": price,
                "timestamp": ts,
                "raw": item,
            }
        )
    return ticks


def _parse_any_ticks(data: Any) -> Iterable[Dict[str, Any]]:
    """
    受信した JSON から、できるだけ多くの tick を抽出する共通ルート。
    - GMO の getRanking 形式（rankingList）を優先的に解釈
    - それ以外は汎用 _extract_tick_generic を使って list/dict を走査
    """
    # まず GMO getRanking 形式をチェック
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        if isinstance(data["result"].get("rankingList"), list):
            ticks = list(_parse_gmo_ranking(data))
            if ticks:
                return ticks

    # 上記で取れなければ汎用パーサ
    ticks: list[Dict[str, Any]] = []
    if isinstance(data, dict):
        t = _extract_tick_generic(data)
        if t:
            ticks.append(t)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                t = _extract_tick_generic(item)
                if t:
                    ticks.append(t)
    return ticks


class GMORealtimeClient:
    """
    GMOクリック CFD の簡易クライアント。

    - mode="websocket":  wss:// に接続して push で受信
    - mode="http":       https:// に定期的に GET して pull で受信

    属性:
      data: Dict[str, Dict] 現在のレートを保持
            {symbol: {"bid":..., "ask":..., "timestamp":..., "raw":...}}
    """

    def __init__(
        self,
        symbols: Optional[list[str]] = None,
        mode: Mode = "websocket",
        poll_interval_sec: float = 1.0,
    ):
        self.symbols = symbols or ["JP225", "NQ100", "XAUUSD", "GER40"]
        self.mode: Mode = mode
        self.poll_interval_sec = poll_interval_sec

        # TODO: DevTools で見つけた URL / ヘッダ / サブスクメッセージをここに貼る

        # WebSocket URL（存在しないなら使わなくてOK）
        self.ws_url: str = os.getenv("GMO_WS_URL", "wss://PUT_REAL_WS_ENDPOINT_HERE")

        # HTTP ポーリング URL（今回の getRanking の URL）
        # 例: https://kabu.click-sec.com/cfd/trade/getRanking?rankingType=1&displayCount=20
        self.http_url: str = os.getenv(
            "GMO_HTTP_URL",
            "https://kabu.click-sec.com/cfd/trade/getRanking?rankingType=1&displayCount=20",
        )

        # Network → Headers から必要なヘッダを転記（User-Agent / Cookie 等）
        self.common_headers: Dict[str, str] = {
            # "User-Agent": "Mozilla/5.0 ...",
            # "Cookie": "JSESSIONID=...; login_status=LOGIN; ...",
        }

        # WebSocket で最初に送る購読メッセージが必要な場合はここに
        self.ws_subscribe_message: Optional[dict] = None

        self.data: Dict[str, Dict] = {}
        self.ws: Optional[websocket.WebSocketApp] = None
        self._stop = False

        val = os.getenv("GMO_WS_VERIFY", "true").lower()
        self.verify_ssl = val not in ("0", "false", "no", "off")

        self._debug_print_count = int(os.getenv("GMO_DEBUG_PRINT_MSGS", "3"))

    # ─────────────────────────────
    # WebSocket コールバック
    # ─────────────────────────────
    def _on_message(self, ws, message: str):
        try:
            msg = json.loads(message)
        except Exception:
            return

        if self._debug_print_count > 0:
            print("📨 GMO WS raw message:", msg)
            self._debug_print_count -= 1

        for tick in _parse_any_ticks(msg):
            symbol = tick["symbol"]
            if symbol in self.symbols:
                self.data[symbol] = {
                    "bid": tick["bid"],
                    "ask": tick["ask"],
                    "timestamp": tick["timestamp"],
                    "raw": tick["raw"],
                }

    def _on_error(self, ws, error):
        print("⚠️ GMO WebSocket error:", error)

    def _on_close(self, ws, *_):
        print("🔌 GMO WebSocket closed")

    def _on_open(self, ws):
        print("✅ GMO WebSocket connected")
        if self.ws_subscribe_message:
            try:
                ws.send(json.dumps(self.ws_subscribe_message))
                print("📨 sent subscribe message:", self.ws_subscribe_message)
            except Exception as e:
                print("⚠️ failed to send subscribe message:", e)

    # ─────────────────────────────
    # 起動 / 停止
    # ─────────────────────────────
    def start(self):
        """バックグラウンドで WebSocket or HTTP を開始"""
        self._stop = False
        if self.mode == "websocket":
            th = threading.Thread(target=self._run_ws_loop, daemon=True)
        else:
            th = threading.Thread(target=self._run_http_loop, daemon=True)
        th.start()

    def stop(self):
        self._stop = True
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass

    # ─────────────────────────────
    # WebSocket ループ
    # ─────────────────────────────
    def _run_ws_loop(self):
        while not self._stop:
            try:
                sslopt = None
                if not self.verify_ssl:
                    print("⚠️ GMO WebSocket: SSL検証を無効化して接続（開発用）")
                    sslopt = {"cert_reqs": ssl.CERT_NONE}

                print(f"🔗 connecting to GMO WS: {self.ws_url}")
                self.ws = websocket.WebSocketApp(
                    self.ws_url,
                    header=[f"{k}: {v}" for k, v in self.common_headers.items()],
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                    on_open=self._on_open,
                )
                self.ws.run_forever(sslopt=sslopt)
            except Exception as e:
                print("⚠️ GMO WS reconnect after error:", e)
                time.sleep(5)

    # ─────────────────────────────
    # HTTP ポーリングループ（getRanking を解析）
    # ─────────────────────────────
    def _run_http_loop(self):
        session = requests.Session()
        session.headers.update(self.common_headers)

        while not self._stop:
            try:
                params: Dict[str, str] = {}
                print(f"📡 GET {self.http_url} params={params}")
                resp = session.get(self.http_url, params=params, timeout=5)
                resp.raise_for_status()
                data = resp.json()

                if self._debug_print_count > 0:
                    print("📨 GMO HTTP raw:", data)
                    self._debug_print_count -= 1

                for tick in _parse_any_ticks(data):
                    symbol = tick["symbol"]
                    if symbol in self.symbols:
                        self.data[symbol] = {
                            "bid": tick["bid"],
                            "ask": tick["ask"],
                            "timestamp": tick["timestamp"],
                            "raw": tick["raw"],
                        }
            except Exception as e:
                print("⚠️ GMO HTTP error:", e)
            finally:
                time.sleep(self.poll_interval_sec)

    # ─────────────────────────────
    # 取得インターフェース
    # ─────────────────────────────
    def get_price(self, symbol: str) -> Optional[Dict]:
        """
        現在の価格情報を返す:
          {"bid":..., "ask":..., "timestamp":..., "raw":...}
        該当シンボルが無ければ None
        """
        return self.data.get(symbol)



# ─────────────────────────────
# 単体テスト用
# ─────────────────────────────
if __name__ == "__main__":
    # まずは HTTP モードで getRanking の JSON を確認するのがおすすめ
    client = GMORealtimeClient(
        symbols=["JP225", "NQ100", "GER40", "XAUUSD"],
        mode="http",          # 必要に応じて "websocket" に変更
        poll_interval_sec=3.0,
    )

    client.start()
    try:
        while True:
            print("----- GMORealtimeClient snapshot -----")
            for sym in client.symbols:
                print(sym, "=>", client.get_price(sym))
            time.sleep(3)
    except KeyboardInterrupt:
        client.stop()
        print("stopped.")
