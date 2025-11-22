#!/usr/bin/env python3
"""
trend_analyzer.py
リアルタイムトレンド分析 - SMA、MACD、RSIで買い/売り判定

DAY6Hシステムと同等以上の精度を目指す
"""

import os
import yfinance as yf
import pandas as pd
from typing import Dict, Literal

# Yahoo Finance シンボルマッピング
SYMBOL_MAP = {
    # Prefer ETF ticker for JP225 to improve data availability and stability
    'JP225': '1321.T',
    'DE40': '^GDAXI',
    'NASDAQ': 'NQ=F',
    'NASDAQ_MINI': 'NQ=F',
    'NQ100': 'NQ=F',
    'SP500': '^GSPC',
    'GOLD': 'GC=F',
    'GOLD_SPOT': 'GC=F',
    'SILVER': 'SI=F',
    'SILVER_SPOT': 'SI=F',
    'NATURAL_GAS': 'NG=F',
    'GAS': 'NG=F',
    'MSFT': 'MSFT',
    'AAPL': 'AAPL'
}

def calculate_trend_signals(symbol: str, period: str = "5d", interval: str = "1h") -> Dict:
    """
    トレンドシグナルを計算
    
    Returns:
        {
            'direction': 'BUY' | 'SELL' | 'NEUTRAL',
            'strength': float (0.0-1.0),
            'sma_signal': 'BUY' | 'SELL' | 'NEUTRAL',
            'macd_signal': 'BUY' | 'SELL' | 'NEUTRAL',
            'rsi': float,
            'price_change_1h': float (%)
            'price_change_4h': float (%)
            'price_change_1d': float (%)
        }
    """
    try:
        yf_symbol = SYMBOL_MAP.get(symbol)
        if not yf_symbol:
            return {'direction': 'NEUTRAL', 'strength': 0.0, 'error': 'Unknown symbol'}
        
        ticker = yf.Ticker(yf_symbol)
        hist = ticker.history(period=period, interval=interval)
        
        if hist.empty or len(hist) < 26:
            return {'direction': 'NEUTRAL', 'strength': 0.0, 'error': 'Insufficient data'}
        
        # 1. SMA計算（短期10, 中期25, 長期75）
        hist['SMA10'] = hist['Close'].rolling(window=10).mean()
        hist['SMA25'] = hist['Close'].rolling(window=25).mean()
        
        # 2. MACD計算
        exp12 = hist['Close'].ewm(span=12, adjust=False).mean()
        exp26 = hist['Close'].ewm(span=26, adjust=False).mean()
        hist['MACD'] = exp12 - exp26
        hist['Signal'] = hist['MACD'].ewm(span=9, adjust=False).mean()
        
        # 3. RSI計算（14期間）
        delta = hist['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        hist['RSI'] = 100 - (100 / (1 + rs))

        # 最新値
        current = hist.iloc[-1]
        prev_4h = hist.iloc[-4] if len(hist) >= 4 else current
        prev_24h = hist.iloc[-24] if len(hist) >= 24 else current

        # 価格変動率
        price_change_1h = ((current['Close'] - hist.iloc[-2]['Close']) / hist.iloc[-2]['Close'] * 100) if len(hist) >= 2 else 0
        price_change_4h = ((current['Close'] - prev_4h['Close']) / prev_4h['Close'] * 100)
        price_change_1d = ((current['Close'] - prev_24h['Close']) / prev_24h['Close'] * 100)

        # SMAシグナル判定
        sma_signal = 'NEUTRAL'
        if pd.notna(current['SMA10']) and pd.notna(current['SMA25']):
            if current['Close'] > current['SMA10'] > current['SMA25']:
                sma_signal = 'BUY'  # 上昇トレンド
            elif current['Close'] < current['SMA10'] < current['SMA25']:
                sma_signal = 'SELL'  # 下降トレンド

        # MACDシグナル判定
        macd_signal = 'NEUTRAL'
        if pd.notna(current['MACD']) and pd.notna(current['Signal']):
            if current['MACD'] > current['Signal'] and current['MACD'] > 0:
                macd_signal = 'BUY'  # 強気
            elif current['MACD'] < current['Signal'] and current['MACD'] < 0:
                macd_signal = 'SELL'  # 弱気

        # RSIシグナル判定
        rsi = current['RSI'] if pd.notna(current['RSI']) else 50
        rsi_signal = 'NEUTRAL'
        if rsi > 70:
            rsi_signal = 'SELL'  # 買われすぎ
        elif rsi < 30:
            rsi_signal = 'BUY'  # 売られすぎ

        # 総合判定（3つのシグナルを統合）
        buy_votes = 0
        sell_votes = 0

        if sma_signal == 'BUY':
            buy_votes += 2  # SMAは重視
        elif sma_signal == 'SELL':
            sell_votes += 2

        if macd_signal == 'BUY':
            buy_votes += 2  # MACDも重視
        elif macd_signal == 'SELL':
            sell_votes += 2

        if rsi_signal == 'BUY':
            buy_votes += 1
        elif rsi_signal == 'SELL':
            sell_votes += 1

        # 短期トレンド（1時間、4時間の変動）も考慮
        if price_change_1h < -0.3 and price_change_4h < -0.5:
            sell_votes += 1  # 短期下落トレンド
        elif price_change_1h > 0.3 and price_change_4h > 0.5:
            buy_votes += 1  # 短期上昇トレンド

        # 最終判定
        total_votes = buy_votes + sell_votes
        if total_votes == 0:
            direction = 'NEUTRAL'
            strength = 0.0
        elif buy_votes > sell_votes:
            direction = 'BUY'
            strength = buy_votes / (buy_votes + sell_votes)
        elif sell_votes > buy_votes:
            direction = 'SELL'
            strength = sell_votes / (buy_votes + sell_votes)
        else:
            direction = 'NEUTRAL'
            strength = 0.5

        result = {
            'direction': direction,
            'strength': strength,
            'sma_signal': sma_signal,
            'macd_signal': macd_signal,
            'rsi_signal': rsi_signal,
            'rsi': float(rsi),
            'price_change_1h': float(price_change_1h),
            'price_change_4h': float(price_change_4h),
            'price_change_1d': float(price_change_1d),
            'current_price': float(current['Close']),
            'sma10': float(current['SMA10']) if pd.notna(current['SMA10']) else None,
            'sma25': float(current['SMA25']) if pd.notna(current['SMA25']) else None,
            'macd': float(current['MACD']) if pd.notna(current['MACD']) else None,
            'macd_signal': float(current['Signal']) if pd.notna(current['Signal']) else None,
            'buy_votes': buy_votes,
            'sell_votes': sell_votes
        }

        # 高精度モード: 現在価格の上書き（アンサンブル）
        if os.getenv('USE_HIGH_ACCURACY', '0') == '1' and symbol == 'JP225':
            try:
                from market_data_ensemble import get_price as ensemble_get_price
                ens = ensemble_get_price('JP225')
                if ens and ens.get('price') is not None:
                    # 解析上は履歴から算出した指標はそのままにして、current_price と乖離メタを上書き
                    result['ensemble_price'] = float(ens['price'])
                    result['ensemble_confidence'] = float(ens.get('confidence', 0.0))
                    # 価格変動率のうち現在価格に依存するものは再計算しておく
                    try:
                        prev_close = hist['Close'].iloc[-2]
                        result['price_change_1h'] = ((ens['price'] - prev_close) / prev_close * 100.0)
                    except Exception:
                        pass
            except Exception:
                # アンサンブル失敗は致命的にしない
                pass

        return result
    
    except Exception as e:
        return {
            'direction': 'NEUTRAL',
            'strength': 0.0,
            'error': str(e)
        }


def get_cut_condition(direction: str, sma_signal: str, macd_signal: str) -> str:
    """
    損切り条件を生成（DAY6H形式）
    """
    if direction == 'BUY':
        return "SMA10<SMA25 or MACD<Signal"
    elif direction == 'SELL':
        return "SMA10>SMA25 or MACD>Signal"
    else:
        return "SMA10!=SMA25 or MACD!=Signal"


if __name__ == "__main__":
    # テスト実行
    test_symbols = ['JP225', 'NASDAQ_MINI', 'DE40', 'GOLD_SPOT']
    
    print("🔍 トレンド分析テスト")
    print("=" * 80)
    
    for symbol in test_symbols:
        result = calculate_trend_signals(symbol)
        
        if 'error' in result:
            print(f"\n❌ {symbol}: {result['error']}")
            continue
        
        direction_icon = {
            'BUY': '🟢 買い',
            'SELL': '🔴 売り',
            'NEUTRAL': '⚪ 中立'
        }
        
        print(f"\n{'='*80}")
        print(f"📊 {symbol} - {direction_icon.get(result['direction'], result['direction'])}")
        print(f"   強度: {result['strength']:.2%}")
        print(f"   現在価格: {result['current_price']:.2f}")
        print(f"   SMA10: {result['sma10']:.2f} | SMA25: {result['sma25']:.2f}")
        print(f"   MACD: {result['macd']:.2f} | Signal: {result['macd_signal']:.2f}")
        print(f"   RSI: {result['rsi']:.1f}")
        print(f"   価格変動: 1H={result['price_change_1h']:+.2f}% | 4H={result['price_change_4h']:+.2f}% | 1D={result['price_change_1d']:+.2f}%")
        print(f"   シグナル: SMA={result['sma_signal']} | MACD={result['macd_signal']} | RSI={result['rsi_signal']}")
        print(f"   投票: 買い={result['buy_votes']} | 売り={result['sell_votes']}")
        print(f"   CUT条件: {get_cut_condition(result['direction'], result['sma_signal'], result['macd_signal'])}")
