#!/bin/bash
# クイックトレンドチェック (メール通知なし版)

cd '/Users/otomi/Desktop/vs code/CFD3_AutoSystem'

./.venv/bin/python3 -c "
from trend_analyzer import calculate_trend_signals
from datetime import datetime
import yfinance as yf

symbols_map = {
    'JP225': '1321.T',
    'NASDAQ': 'NQ=F',
    'GOLD': 'GC=F',
    'SILVER': 'SI=F',
    'NATURAL_GAS': 'NG=F',
    'DE40': '^GDAXI'
}

print('━' * 80)
print(f'🔍 トレンドクイックチェック - {datetime.now().strftime(\"%H:%M:%S\")}')
print('━' * 80)
print()

for sym, ticker in symbols_map.items():
    try:
        # 短期トレンド
        trend = calculate_trend_signals(sym, period='7d', interval='15m')
        direction = trend['direction']
        strength = trend['strength'] * 100
        
        # 価格取得
        try:
            data = yf.Ticker(ticker)
            hist = data.history(period='1d', interval='1m')
            price = hist['Close'].iloc[-1] if not hist.empty else 0
        except:
            price = 0
        
        # 表示
        if direction == 'BUY':
            emoji = '🟢'
            alert = ' ⚠️ 売りポジション反転!' if strength >= 80 else ''
        elif direction == 'SELL':
            emoji = '🔴'
            alert = ' ⚠️ 買いポジション反転!' if strength >= 80 else ''
        else:
            emoji = '⚪'
            alert = ' トレンド消失' if strength == 0 else ''
        
        status = '✅ 強い' if strength >= 80 else ('△ 中程度' if strength >= 50 else '❌ 弱い')
        
        print(f'{emoji} {sym:12} {direction:7} {strength:5.1f}% {status}{alert}')
        if price > 0:
            print(f'   価格: {price:,.2f}')
        
    except Exception as e:
        print(f'❌ {sym}: {e}')

print()
print('━' * 80)
print('💡 1時間ごとに実行推奨: ./quick_trend_check.sh')
print('━' * 80)
"
