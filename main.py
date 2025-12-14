from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Korean Grammar API")

# --- データ例 ---
GRAMMAR = {
    1: {
        "title": "〜아요/어요",
        "explanation": "動詞・形容詞の基本的な丁寧形です。",
        "example": "먹어요 / 가요"
    }
}

QUIZ = {
    1: {
        "question": "「食べます」はどれ？",
        "choices": ["먹다", "먹어요", "먹었습니다"],
        "answer": 1
    }
}

# --- モデル ---
class QuizAnswer(BaseModel):
    choice: int

# --- エンドポイント ---
@app.get("/")
def health():
    return {"status": "ok"}


@app.get("/api/grammar/{unit}")
def get_grammar(unit: int):
    return GRAMMAR.get(unit, {"error": "not found"})


@app.get("/api/quiz/{unit}")
def get_quiz(unit: int):
    q = QUIZ.get(unit)
    if not q:
        return {"error": "not found"}
    return {
        "question": q["question"],
        "choices": q["choices"]
    }


@app.post("/api/quiz/{unit}")
def answer_quiz(unit: int, body: QuizAnswer):
    q = QUIZ.get(unit)
    if not q:
        return {"error": "not found"}
    correct = body.choice == q["answer"]
    return {"correct": correct}
