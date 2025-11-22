#!/usr/bin/env python3
"""
IFD注文をCSVスクショシステム形式に変換

現在のIFD生成結果を、GMO CFD自動発注用のJSON形式に変換します。
"""
import sys, os, json
from datetime import datetime
from typing import Dict, Any, List

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from mygpt_strategy import analyze_signal

# 銘柄リスト
SYMBOLS = ["JP225", "NQ100", "XAUUSD", "XAGUSD", "NGAS", "GER40"]

def get_price_from_env_or_yf(symbol: str) -> float | None:
    """環境変数 or yfinance から価格取得"""
    import yfinance as yf
    from app.config import YF_SYMBOL_OVERRIDES
    
    env_key = f"PRICE_{symbol}"
    if env_key in os.environ:
        try:
            return float(os.environ[env_key])
        except Exception:
            pass
    
    yf_sym = YF_SYMBOL_OVERRIDES.get(symbol) or {
        "JP225": "^N225", "NQ100": "^NDX", "XAUUSD": "GC=F",
        "XAGUSD": "SI=F", "NGAS": "NG=F", "GER40": "^GDAXI"
    }.get(symbol)
    
    if not yf_sym:
        return None
    
    try:
        ticker = yf.Ticker(yf_sym)
        hist = ticker.history(period="1d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return None

def fetch_news_if_available(symbol: str) -> tuple[list, float]:
    """ニュース取得（オプション）"""
    try:
        from app.news_collector import get_news_for_symbol
        items = get_news_for_symbol(symbol, limit=10)
        if items and len(items) > 0:
            # sentiment計算（簡易）
            from textblob import TextBlob
            scores = []
            for item in items:
                try:
                    text = item.get("title", "") + " " + item.get("description", "")
                    blob = TextBlob(text)
                    scores.append(blob.sentiment.polarity)
                except Exception:
                    pass
            sentiment = sum(scores) / len(scores) if scores else 0.0
            return items, sentiment
    except Exception:
        pass
    return [], 0.0

# CSVスクショシステム用の設定
CAPITAL_JPY = int(os.getenv("CAPITAL_JPY", "900000"))
PER_LOT_JPY = int(os.getenv("PER_LOT_JPY", "300000"))
TRADE_MODE = os.getenv("TRADE_MODE", "DAY6H")

# レーティング → signal_rating (1-10) の変換
def rating_to_signal_rating(rating: float) -> int:
    """rating (0-10) を signal_rating (1-10) に変換"""
    return max(1, min(10, int(round(rating))))

# 銘柄 → instrument の変換（CSVスクショでは同じ名前を使用）
INSTRUMENT_MAP = {
    "JP225": "JP225",
    "NQ100": "NQ100",
    "XAUUSD": "XAUUSD",
    "XAGUSD": "XAGUSD",
    "NGAS": "NGAS",
    "GER40": "GER40",
}

# side → direction の変換
def side_to_direction(side: str) -> str:
    return side.lower()  # BUY → buy, SELL → sell

# rating → lots の算出
def calculate_lots(rating: float, decision: str) -> int:
    """レーティングとdecisionに基づいてロット数を決定"""
    if decision == "STRONG_GO":
        return 4  # 高信頼度
    elif decision == "GO":
        return 3  # 中信頼度
    else:
        return 2  # 低信頼度（通常は発注しないが保険）

# entry_order タイプの決定
def determine_order_type(decision: str, rating: float) -> tuple[str, str]:
    """
    decision と rating から注文タイプを決定
    Returns: (order_type_ja, order_type_en)
    """
    if decision == "STRONG_GO" and rating >= 6.0:
        return ("成行", "market")
    else:
        return ("指値", "limit")

# IFD legs の生成（現在は単純な2段階を想定）
def generate_ifd_legs(entry: float, tp: float, sl: float, side: str, rating: float) -> List[Dict[str, Any]]:
    """
    2段階のIFD-OCOを生成
    - IFD-1: 基本TP/SL
    - IFD-2: 拡張TP + トレーリングストップ
    """
    legs = []
    
    # IFD-1: 基本TP/SL
    legs.append({
        "name": "IFD-1",
        "oco": {
            "take_profit": {"price": round(tp, 2)},
            "stop_loss": {"price": round(sl, 2)}
        }
    })
    
    # IFD-2: 高信頼度の場合のみ拡張TP + トレーリング
    if rating >= 5.0:
        extended_tp = tp * 1.005 if side == "BUY" else tp * 0.995  # TP を 0.5% 延長
        trailing_distance = abs(entry - sl) * 0.3  # SL幅の30%をトレーリング幅に
        
        legs.append({
            "name": "IFD-2",
            "oco": {
                "take_profit": {"price": round(extended_tp, 2)},
                "stop_loss": {"price": round(sl, 2)},
                "trailing_stop": {
                    "activate_after": round(tp, 2),
                    "distance": round(trailing_distance, 2)
                }
            }
        })
    
    return legs

# カット条件の生成（screenerデータから）
def generate_cut_condition(screener: Dict[str, Any] | None) -> Dict[str, str]:
    """
    Screenerデータに基づいてカット条件を生成
    """
    if not screener:
        return {}
    
    sma25 = screener.get("SMA25")
    sma75 = screener.get("SMA75")
    macd = screener.get("MACD")
    macd_sig = screener.get("MACD_signal")
    
    conditions = {}
    
    # SMA条件
    if sma25 and sma75:
        if sma25 > sma75:
            conditions["sma"] = "SMA25<SMA75"  # 上昇トレンド中は下抜けでカット
        else:
            conditions["sma"] = "SMA25>SMA75"  # 下降トレンド中は上抜けでカット
    
    # MACD条件
    if macd and macd_sig:
        if macd > macd_sig:
            conditions["macd"] = "MACD<Signal"  # 上昇中は下抜けでカット
        else:
            conditions["macd"] = "MACD>Signal"  # 下降中は上抜けでカット
    
    return conditions

def convert_to_csv_screenshot_format(threshold: str = "GO") -> Dict[str, Any]:
    """
    現在のIFD生成結果をCSVスクショ形式に変換
    
    Args:
        threshold: "GO" or "STRONG_GO" - この閾値以上のみ出力
    """
    run_id = datetime.now().strftime("%Y-%m-%d-%H%M")
    
    orders = []
    
    for s in SYMBOLS:
        # 価格取得
        price = get_price_from_env_or_yf(s)
        if price is None:
            continue
        
        # ニュース取得（オプション）
        news_items, sentiment = fetch_news_if_available(s)
        
        # 分析実行
        payload = {
            "symbol": s,
            "price": price,
            "signal": "STRONG_GO",  # 仮の初期値
            "news_items": news_items,
            "sentiment_score": sentiment,
        }
        
        analysis = analyze_signal(s, payload)
        decision = analysis.get("decision")
        rating = analysis.get("rating", 0)
        side = analysis.get("side", "BUY")
        
        # 閾値チェック
        if decision not in (threshold, "STRONG_GO"):
            if threshold == "GO" and decision != "GO":
                continue
            elif threshold == "STRONG_GO":
                continue
        
        # IFD生成
        from mygpt_strategy import generate_ifd, TP_SL_RATES
        
        if s not in TP_SL_RATES:
            continue
        
        ifd = generate_ifd(s, price, decision, meta=analysis, side=side)
        
        # CSVスクショ形式に変換
        order_type_ja, order_type_en = determine_order_type(decision, rating)
        lots = calculate_lots(rating, decision)
        
        order = {
            "instrument": INSTRUMENT_MAP.get(s, s),
            "direction": side_to_direction(side),
            "signal_rating": rating_to_signal_rating(rating),
            "decision": decision,
            "lots": lots,
            "entry_order": {
                "type": order_type_en,
                "price": round(price, 2)
            },
            "order_type": order_type_ja,
            "ifd_legs": generate_ifd_legs(
                price,
                ifd["take_profit"],
                ifd["stop_loss"],
                side,
                rating
            ),
            "cut_condition": generate_cut_condition(analysis.get("screener"))
        }
        
        orders.append(order)
    
    # 最終JSON構築
    result = {
        "run_id": run_id,
        "capital_jpy": CAPITAL_JPY,
        "per_lot_allocation_jpy": PER_LOT_JPY,
        "trade_mode": TRADE_MODE,
        "orders": orders
    }
    
    return result

def main():
    import argparse
    parser = argparse.ArgumentParser(description="IFD → CSVスクショ形式変換")
    parser.add_argument("--threshold", default="GO", choices=["GO", "STRONG_GO"],
                        help="出力する最低判定レベル")
    parser.add_argument("--output", default="output/csv_screenshot_orders.json",
                        help="出力JSONファイルパス")
    args = parser.parse_args()
    
    print(f"🔄 Generating CSV Screenshot format (threshold={args.threshold})...")
    
    result = convert_to_csv_screenshot_format(threshold=args.threshold)
    
    # 出力
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"✅ Generated {len(result['orders'])} orders")
    print(f"📄 Saved to: {args.output}")
    
    # 簡易サマリー
    if result['orders']:
        print("\n📊 Orders Summary:")
        for o in result['orders']:
            print(f"  - {o['instrument']}: {o['direction'].upper()} @ {o['entry_order']['price']} "
                  f"(rating={o['signal_rating']}, lots={o['lots']})")
    else:
        print("\n⚠️ No orders generated (no symbols meet threshold)")

if __name__ == "__main__":
    main()
