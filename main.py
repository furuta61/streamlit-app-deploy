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

app = FastAPI(
    title="Korean Grammar Quiz API",
    version="0.1.0"
)


@app.get("/")
def health():
    return {"status": "ok"}


@app.get("/api/quiz")
def quiz(unit: int = 1):
    return {
        "unit": unit,
        "question": "「食べます」の丁寧な過去形はどれ？",
        "choices": [
            "먹어요",
            "먹었습니다",
            "먹을 거예요",
            "먹고 있어요"
        ],
        "answer": 2
    }
    return quizzes.get(unit, {

        "error": "その unit は存在しません"

    })
