#!/usr/bin/env python3
"""
リアルタイムCSVスクショシステム
- 毎回リアルタイム価格でCSVを生成
- スクショをGmail添付
- 古いevents.csvを使わない
"""

import pandas as pd
from datetime import datetime
from pathlib import Path
import io

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = None
    ImageDraw = None
    ImageFont = None

ROOT = Path(__file__).parent


def generate_realtime_csv():
    """リアルタイム価格でCSV生成"""
    from market_data_fetch import get_latest_prices
    
    print("📊 リアルタイム価格取得中...")
    prices = get_latest_prices()
    
    # 現在時刻のイベントとして記録
    event_time = datetime.now()
    
    # CSVデータ作成
    data = {
        'text': f'Real-time Signal Check - {event_time.strftime("%Y-%m-%d %H:%M")}',
        'date': event_time.strftime('%Y-%m-%d %H:%M:%S'),
        'combined_score': 0.90,  # リアルタイムシグナル
        'GOLD': prices.get('GOLD', 0),
        'USDJPY': prices.get('USDJPY', 0),
        'NASDAQ': prices.get('NASDAQ', 0),
        'JP225': prices.get('JP225', 0),
        'SP500': prices.get('SP500', 0),
        'DE40': prices.get('DE40', 0),
        'AAPL': prices.get('AAPL', 0),
        'MSFT': prices.get('MSFT', 0),
        'SILVER': prices.get('SILVER', 0),
        'NATURAL_GAS': prices.get('NATURAL_GAS', 0)
    }
    
    df = pd.DataFrame([data])
    
    # 一時CSVファイルに保存
    csv_path = ROOT / f'realtime_signal_{event_time.strftime("%Y%m%d_%H%M%S")}.csv'
    df.to_csv(csv_path, index=False)
    
    print(f"✅ CSV生成: {csv_path}")
    return csv_path, df


def create_csv_screenshot(df, output_path):
    """CSVをスクリーンショット画像化"""
    # テキストとして整形
    text = df.to_string(index=False)
    
    # 画像サイズ計算
    font_size = 14
    line_height = font_size + 4
    lines = text.split('\n')
    max_width = max(len(line) for line in lines) * (font_size // 2 + 2)
    height = len(lines) * line_height + 40
    
    # 画像作成
    img = Image.new('RGB', (max_width, height), color='white')
    draw = ImageDraw.Draw(img)
    
    # テキスト描画（デフォルトフォント使用）
    y = 20
    for line in lines:
        draw.text((10, y), line, fill='black')
        y += line_height
    
    # 保存
    img.save(output_path)
    print(f"📸 スクショ作成: {output_path}")
    return output_path


def main():
    """メイン処理"""
    print("=" * 60)
    print("📸 リアルタイムCSVスクショシステム")
    print("=" * 60)
    
    # 1. リアルタイムCSV生成
    csv_path, df = generate_realtime_csv()
    
    # 2. スクショ作成
    screenshot_path = csv_path.with_suffix('.png')
    create_csv_screenshot(df, screenshot_path)
    
    # 3. IFD分析実行
    print("\n🔄 IFD分析実行中...")
    import subprocess
    import sys
    
    cmd = [sys.executable, str(ROOT / 'cfd3_ifd_daytrade.py')]
    env = {'EVENTS_CSV_OVERRIDE': str(csv_path)}
    
    result = subprocess.run(cmd, cwd=str(ROOT), env=env, 
                          capture_output=True, text=True)
    
    print(result.stdout)
    
    print("\n✅ リアルタイム分析完了")
    print(f"📎 CSV: {csv_path}")
    print(f"📎 スクショ: {screenshot_path}")
    print("=" * 60)
    
    return csv_path, screenshot_path


if __name__ == '__main__':
    main()
