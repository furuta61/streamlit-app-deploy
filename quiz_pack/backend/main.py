"""FastAPI エントリポイント
 - /api/quiz: 単元別のフル問題バンク取得 (explanation/mcq/cloze/writing)
 - /api/explain (POST/GET): 文法説明取得（POST は Streamlit 簡易 UI 用）
 - /api/exercise: 軽量 3問（MCQ / Cloze / Writing）パック生成（採点なし UI 用）
 - /api/grade: 語幹一致対応の拡張採点（単一 QA）
"""
from fastapi import FastAPI, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
# 相対インポートに変更（ルートからの 'backend' 参照問題回避）
from .quiz_generator import (
    generate_explanation,
    generate_mcq,
    generate_cloze,
    generate_writing,
    generate_concept_cloze,
)
from .rules import rules
from .judge import grade_answer  # 新採点ロジック

app = FastAPI(title="Korean Grammar Quiz API", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8501",
        "https://korean-grammar-api.onrender.com",
        "*",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class QuizRequest(BaseModel):
    unit: str
    tone: str = "standard"

@app.get("/api/health")
def health():
    return {"ok": True}

@app.post("/api/quiz")
def _normalize_unit(unit: str) -> str:
    # 単元キー正規化: 「文法20」「G20」「mcq_G20」などから数字部分を抽出
    import re
    m = re.search(r"(\d{1,2})", unit)
    return m.group(1) if m else unit


def quiz(req: QuizRequest):
    u = _normalize_unit(req.unit)
    return {
        "explanation": generate_explanation(u, req.tone),
        "mcq": generate_mcq(u, req.tone),
        "cloze": generate_cloze(u, req.tone),
        "writing": generate_writing(u, req.tone),
    }


@app.post("/api/explain")
def explain(req: QuizRequest):
    u = _normalize_unit(req.unit)
    unit_rules = rules.get(u, {})
    text = unit_rules.get(req.tone)
    if not text:
        # fallback to standard if tone not found, then generic message
        text = unit_rules.get("standard") or "該当する文法説明が見つかりません。"
    return {"unit": u, "tone": req.tone, "text": text}


@app.get("/api/explain")
def explain_get(unit: str = Query(...), tone: str = Query("standard")):
    """互換 GET 版。既存ツールやブラウザ直接確認用。"""
    u = _normalize_unit(unit)
    unit_rules = rules.get(u, {})
    text = unit_rules.get(tone)
    if not text:
        text = unit_rules.get("standard") or "該当する文法説明が見つかりません。"
    return {"unit": u, "tone": tone, "text": text}


class ExerciseRequest(BaseModel):
    unit: str
    tone: str = "standard"
    type: str = "all"  # "mcq" | "cloze" | "concept" | "writing" | "all"

@app.post("/api/exercise")
def exercise(req: ExerciseRequest):
    """簡易練習問題セットを返す。
    - type="mcq": 四択問題のみ
    - type="cloze": 穴埋め問題のみ
    - type="concept": 概念理解問題のみ
    - type="writing": 作文問題のみ
    - type="all": 全種類（デフォルト）
    UI では採点無し前提。
    """
    # 全種類の問題を生成
    u = _normalize_unit(req.unit)
    mcqs = generate_mcq(u, req.tone)
    clozes = generate_cloze(u, req.tone)
    concept = generate_concept_cloze(u)  # tone 非依存（混乱防止のため標準）
    writings = generate_writing(u, req.tone)

    items = []
    
    # type に応じてフィルタリング
    if req.type in ["mcq", "all"] and mcqs:
        first = mcqs[0].copy()
        first["type"] = "mcq"
        items.append({
            "question": first.get("question"),
            "choices": first.get("choices", []),
            "answer": first.get("answer"),
            "explanation": first.get("explanation", ""),
            "type": "mcq",
        })
    
    if req.type in ["cloze", "all"] and clozes:
        c0 = clozes[0].copy()
        # distractors + 正答を提示（UI は選択一覧があれば表示する想定）
        choices = list({c0.get("answer", "")} | set(c0.get("distractors", [])))
        items.append({
            "question": c0.get("question"),
            "choices": choices,
            "answer": c0.get("answer"),
            "pattern": c0.get("pattern"),
            "concept": c0.get("concept"),
            "explanation": c0.get("explanation", ""),
            "type": "cloze",
        })
    
    # 概念理解（日本語メタ問題）を 1 問追加（存在する場合）
    if req.type in ["concept", "all"] and concept:
        c = concept[0]
        items.append({
            "type": "concept",
            "question": c.get("question"),
            "choices": c.get("choices", []),
            "answer": c.get("answer", []),
        })
    
    if req.type in ["writing", "all"] and writings:
        w0 = writings[0].copy()
        items.append({
            "question": w0.get("instruction"),
            "choices": [],
            "answer": w0.get("answer"),
            "explanation": w0.get("explanation", ""),
            "type": "writing",
        })

    return {"unit": u, "tone": req.tone, "type": req.type, "count": len(items), "items": items}


@app.post("/api/grade")
async def api_grade(request: Request):
    """拡張採点API: user_answer, correct_answer を受け取り語幹一致判定などを含むスコアを返す。
    互換性維持のため旧形式(items)が来た場合は最初の要素を評価。
    入力例:
      {"user_answer":"문을 닫고있어요", "correct_answer":"문을 닫고 있어요"}
    戻り例:
      {"ok":True,"result":{"correct":True,"score":0.9,"mode":"語幹一致"}}
    """
    data = await request.json()
    # 旧形式互換: items=[{question, selected}], unit,tone → MCQ 正答再取得
    if "items" in data and isinstance(data.get("items"), list):
        items = data.get("items")
        unit = _normalize_unit(data.get("unit", ""))
        tone = data.get("tone", "standard")
        if items:
            first = items[0]
            q = first.get("question")
            sel = first.get("selected")
            # 正答を再生成
            bank = {m["question"]: m for m in generate_mcq(unit, tone)}
            correct = (bank.get(q) or {}).get("answer", "")
            # MCQ は厳密一致（語幹/部分一致は選択肢式では緩すぎるため除外）
            is_exact = sel == correct
            result = {
                "correct": is_exact,
                "score": 1.0 if is_exact else 0.0,
                "mode": "選択一致" if is_exact else "不一致",
            }
            # 旧仕様互換フィールド整備
            legacy_results = [{
                "question": q,
                "selected": sel,
                "isCorrect": result["correct"],
                "expected": correct,
                "mode": result["mode"],
                "score": result["score"],
            }]
            return {
                "ok": True,
                "legacy": True,
                "result": result,
                "question": q,
                "correct_answer": correct,
                "correct": int(result["correct"]),
                "total": 1,
                "results": legacy_results,
            }
    # 新形式
    user = data.get("user_answer", "")
    correct = data.get("correct_answer", "")
    result = grade_answer(user, correct)
    return {"ok": True, "result": result}
