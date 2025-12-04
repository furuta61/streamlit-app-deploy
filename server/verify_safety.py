#!/usr/bin/env python3
"""
500%安全性検証ツール - 5ステップ検証
"""
import re
import sys
from pathlib import Path

def check_1_variable_scope():
    """✅ 検証① - 関数レベルのスコープ健全性"""
    print("\n" + "="*60)
    print("✅ 検証① - 変数スコープの健全性チェック")
    print("="*60)
    
    target = Path(__file__).parent / "webhook_server.py"
    content = target.read_text()
    
    # entry, results, parsed などの重要変数が関数の最初で初期化されているか
    functions = re.findall(r'(async\s+)?def\s+(\w+)\s*\([^)]*\):(.*?)(?=\n(?:async\s+)?def\s+|\Z)', content, re.DOTALL)
    
    issues = []
    for async_kw, func_name, func_body in functions:
        if func_name.startswith("_"):
            continue
            
        # results, entry, parsed などを探す
        for var in ["results", "entry", "parsed"]:
            if var in func_body:
                # 最初に使われている行を探す
                lines = func_body.split('\n')
                first_use = None
                first_assign = None
                
                for i, line in enumerate(lines):
                    if var in line:
                        if first_use is None:
                            first_use = i
                        if f"{var} =" in line or f"{var}=" in line:
                            if first_assign is None:
                                first_assign = i
                
                if first_use is not None and first_assign is not None:
                    if first_use < first_assign:
                        issues.append(f"  ⚠️ {func_name}(): '{var}' が代入前に使用されています（使用={first_use}行目, 代入={first_assign}行目）")
    
    if issues:
        print("\n".join(issues))
        return False
    else:
        print("✅ すべての変数が適切に初期化されています")
        return True

def check_2_return_consistency():
    """✅ 検証② - 戻り値の一貫性"""
    print("\n" + "="*60)
    print("✅ 検証② - 戻り値の一貫性チェック")
    print("="*60)
    
    target = Path(__file__).parent / "webhook_server.py"
    content = target.read_text()
    
    # analyze_image, analyze_sentiment などの関数で return が dict かチェック
    functions = ["analyze_image", "analyze_sentiment", "ai_unified_decision", "analyze_news_sentiment"]
    
    issues = []
    for func in functions:
        pattern = rf'(async\s+)?def\s+{func}\s*\([^)]*\):(.*?)(?=\n(?:async\s+)?def\s+|\Z)'
        match = re.search(pattern, content, re.DOTALL)
        
        if match:
            func_body = match.group(2)
            returns = re.findall(r'return\s+(.+)', func_body)
            
            for ret in returns:
                ret = ret.strip()
                # dict型か確認（簡易チェック）
                if not ret.startswith('{') and 'dict' not in ret and ret not in ['None', 'False', 'True']:
                    # safe_dict() で包まれているかチェック
                    if 'safe_dict' not in ret and 'safe_gpt_json' not in ret:
                        issues.append(f"  ⚠️ {func}(): 戻り値が dict でない可能性: {ret[:50]}")
    
    if issues:
        print("\n".join(issues))
        return False
    else:
        print("✅ すべての戻り値が安全に処理されています")
        return True

def check_3_exception_handling():
    """✅ 検証③ - 例外ハンドリング構造"""
    print("\n" + "="*60)
    print("✅ 検証③ - 例外ハンドリングの完全性")
    print("="*60)
    
    target = Path(__file__).parent / "webhook_server.py"
    content = target.read_text()
    
    # FastAPI エンドポイント（@app.post, @app.get）に try-except があるか
    endpoints = re.findall(r'@app\.(post|get)\s*\([^)]+\)\s*\nasync\s+def\s+(\w+)\s*\([^)]*\):(.*?)(?=\n@app\.|\Z)', content, re.DOTALL)
    
    issues = []
    for method, func_name, func_body in endpoints:
        if 'try:' not in func_body:
            issues.append(f"  ⚠️ {func_name}(): try-except ブロックがありません")
        elif 'except Exception' not in func_body and 'except:' not in func_body:
            issues.append(f"  ⚠️ {func_name}(): 汎用例外処理がありません")
        
        # JSON応答をしているか
        if '{"status"' not in func_body and "{'status'" not in func_body:
            issues.append(f"  ⚠️ {func_name}(): JSON形式の応答がありません")
    
    if issues:
        print("\n".join(issues))
        return False
    else:
        print("✅ すべてのエンドポイントが適切に例外処理されています")
        return True

def check_4_type_safe():
    """✅ 検証④ - タイプセーフチェック"""
    print("\n" + "="*60)
    print("✅ 検証④ - .get() 呼び出しの型安全性")
    print("="*60)
    
    target = Path(__file__).parent / "webhook_server.py"
    content = target.read_text()
    
    # .get( を検索
    get_calls = re.findall(r'(\w+)\.get\s*\(', content)
    
    issues = []
    unsafe_vars = []
    
    for var in get_calls:
        # safe_get, safe_dict で包まれていない生の .get() を探す
        # ただし、dict型が保証されているものは除外
        if var not in ['dict', 'os', 'request', 'headers', 'params']:
            # その変数が safe_dict() で初期化されているか確認
            if f"{var} = safe_dict" not in content and f"{var} = safe_gpt_json" not in content:
                if f"isinstance({var}, dict)" not in content:
                    unsafe_vars.append(var)
    
    if unsafe_vars:
        unique = list(set(unsafe_vars))
        issues.append(f"  ⚠️ 型チェックなしの.get()呼び出し: {', '.join(unique)}")
        print("\n".join(issues))
        return False
    else:
        print("✅ すべての .get() 呼び出しが安全です")
        return True

def check_5_ui_spinner():
    """✅ 検証⑤ - UI側スピン制御"""
    print("\n" + "="*60)
    print("✅ 検証⑤ - フロントエンドのスピナー制御")
    print("="*60)
    
    target = Path(__file__).parent / "templates/ui_final.html"
    content = target.read_text()
    
    issues = []
    
    # analyzeWithImage, analyzeUnified 関数をチェック
    functions = ["analyzeWithImage", "analyzeUnified"]
    
    for func in functions:
        pattern = rf'async\s+function\s+{func}\s*\([^)]*\)\s*\{{(.*?)\}}\s*(?=async\s+function|\</script)'
        match = re.search(pattern, content, re.DOTALL)
        
        if match:
            func_body = match.group(1)
            
            # spinner.style.display = "block" があるか
            if 'spinner.style.display = "block"' not in func_body and 'spinner.style.display="block"' not in func_body:
                issues.append(f"  ⚠️ {func}(): スピナー表示処理がありません")
            
            # catch ブロックで spinner を閉じているか
            if 'catch' in func_body:
                catch_block = re.search(r'catch\s*\([^)]*\)\s*\{(.*?)\}', func_body, re.DOTALL)
                if catch_block:
                    if 'spinner.style.display = "none"' not in catch_block.group(1):
                        issues.append(f"  ⚠️ {func}(): catch ブロックでスピナーを閉じていません")
    
    if issues:
        print("\n".join(issues))
        return False
    else:
        print("✅ フロントエンドのスピナー制御は完璧です")
        return True

def main():
    print("\n" + "🔍"*30)
    print("  500% 安全性検証ツール")
    print("🔍"*30)
    
    results = []
    results.append(("変数スコープ", check_1_variable_scope()))
    results.append(("戻り値一貫性", check_2_return_consistency()))
    results.append(("例外ハンドリング", check_3_exception_handling()))
    results.append(("型安全性", check_4_type_safe()))
    results.append(("UIスピナー", check_5_ui_spinner()))
    
    print("\n" + "="*60)
    print("📊 検証結果サマリー")
    print("="*60)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{name:20s} : {status}")
    
    all_pass = all(r[1] for r in results)
    
    print("\n" + "="*60)
    if all_pass:
        print("🎉 500% 安全性検証 - すべて合格！")
        print("="*60)
        return 0
    else:
        print("⚠️ 一部の検証が失敗しました。上記の警告を確認してください。")
        print("="*60)
        return 1

if __name__ == "__main__":
    sys.exit(main())
