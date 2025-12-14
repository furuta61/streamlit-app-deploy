from fastapi import FastAPI, Query

app = FastAPI(
    title="Korean Grammar Quiz API",
    description="韓国語文法の解説とクイズを返すAPI",
    version="0.1.0"
)

# -------------------------
# Health Check
# -------------------------
@app.get("/")
def health():
    return {"status": "ok"}

@app.get("/api/health")
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(
    title="Korean Grammar API",
    version="0.1.0",
    description="韓国語の文法解説と簡単なクイズAPI"
)

# -------------------
# Health check
# -------------------
@app.get("/")
def health():
    return {"status": "ok"}

# -------------------
# 文法解説
# -------------------
@app.get("/api/grammar")
def grammar(unit: int = 1):
    data = {
        1: {
            "title": "〜아요／어요",
            "explanation": "動詞・形容詞の丁寧な現在形です。",
            "example": "먹어요（食べます） / 가요（行きます）"
        },
        2: {
            "title": "〜고 있어요",
            "explanation": "進行形を表します。",
            "example": "공부하고 있어요（勉強しています）"
        }
    }
    return data.get(unit, {"error": "そのユニットはありません"})

# -------------------
# クイズ
# -------------------
class Answer(BaseModel):
    answer: str


@app.get("/api/quiz")
def quiz(unit: int = 1):
    quizzes = {
        1: {
            "question": "「食べます」は韓国語で？",
            "choices": ["먹어요", "먹었어요", "먹을 거예요"],
            "correct": "먹어요"
        }
    }
    q = quizzes.get(unit)
    if not q:
        return {"error": "クイズがありません"}
    return {
        "question": q["question"],
        "choices": q["choices"]
    }


@app.post("/api/quiz")
def check_quiz(unit: int, data: Answer):
    correct = "먹어요"
    return {
        "result": data.answer == correct,
        "correct_answer": correct
    }
    return quizzes.get(unit, {

        "error": "その unit は存在しません"

    })
