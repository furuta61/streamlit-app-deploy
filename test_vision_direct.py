#!/usr/bin/env python3
"""
FastAPI /analyze/image エンドポイントへの直接テスト送信
"""
import requests
import sys
from io import BytesIO

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = None
    ImageDraw = None
    ImageFont = None

def create_test_image():
    """テスト用の簡単な画像を生成（チャート風）"""
    if Image is None:
        print("Pillowなし → Renderではローカル画像テストは無効")
        return None
    img = Image.new('RGB', (800, 600), color='white')
    draw = ImageDraw.Draw(img)
    
    # シンプルなチャート風の線を描画
    draw.rectangle([50, 50, 750, 550], outline='black', width=2)
    draw.line([100, 300, 200, 250, 300, 350, 400, 200, 500, 280, 600, 230, 700, 300], fill='blue', width=3)
    
    # テキスト情報を追加
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 40)
    except:
        font = ImageFont.load_default()
    
    draw.text((100, 100), "TEST CHART - JP225", fill='black', font=font)
    draw.text((100, 450), "Entry: 23278.0", fill='green', font=font)
    draw.text((100, 500), "Direction: BUY", fill='blue', font=font)
    
    # BytesIO に保存
    buffer = BytesIO()
    img.save(buffer, format='JPEG')
    buffer.seek(0)
    return buffer

def test_vision_api(image_file, api_url="http://localhost:8080/analyze/image"):
    """FastAPI の /analyze/image に画像を送信"""
    
    print(f"🚀 FastAPI Vision API テスト送信")
    print(f"📍 URL: {api_url}")
    print(f"📸 画像: {type(image_file).__name__}")
    print("-" * 60)
    
    files = {
        'file': ('test_chart.jpg', image_file, 'image/jpeg')
    }
    params = {
        'symbol': 'JP225'
    }
    
    try:
        print("⏳ リクエスト送信中...")
        response = requests.post(api_url, files=files, params=params, timeout=60)
        
        print(f"✅ ステータスコード: {response.status_code}")
        print("-" * 60)
        
        if response.status_code == 200:
            result = response.json()
            print("📊 レスポンス内容:")
            print(f"  - ステータス: {result.get('status')}")
            print(f"  - シンボル: {result.get('symbol')}")
            
            if 'analysis' in result:
                analysis = result['analysis']
                print(f"\n🧠 AI解析結果:")
                print(f"  - entry: {analysis.get('entry')}")
                print(f"  - direction: {analysis.get('direction')}")
                print(f"  - confidence: {analysis.get('confidence')}")
                print(f"  - reasoning: {analysis.get('reasoning', 'なし')[:100]}")
                
                if 'raw_text' in analysis:
                    print(f"\n📝 生レスポンス (最初の300文字):")
                    print(analysis['raw_text'][:300])
            
            if 'ifd' in result:
                ifd = result['ifd']
                print(f"\n📋 IFD生成結果:")
                if 'orders' in ifd:
                    for order in ifd['orders']:
                        if order.get('order_type') == 'ENTRY':
                            print(f"  - エントリー価格: {order.get('price')}")
                            print(f"  - 方向: {order.get('direction')}")
                        elif order.get('order_type') == 'IFD_LEG':
                            print(f"  - TP: {order.get('take_profit')}")
                            print(f"  - SL: {order.get('stop_loss')}")
                else:
                    print(f"  - エラー: {ifd.get('error', '不明')}")
            
            print("\n" + "=" * 60)
            print("✅ テスト完了 - Vision API 正常動作")
            return True
            
        else:
            print(f"❌ エラー: {response.status_code}")
            print(response.text[:500])
            return False
            
    except Exception as e:
        print(f"❌ 例外発生: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    # テスト画像を生成
    print("🖼️  テスト画像を生成中...")
    test_image = create_test_image()
    
    # FastAPI にリクエスト送信
    success = test_vision_api(test_image)
    
    sys.exit(0 if success else 1)
