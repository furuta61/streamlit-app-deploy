# -- coding: utf-8 --
"""
pytest for Korean Grammar Quiz System (現行API適合版)
目的:
  - 文法19〜25の /api/quiz が正常応答するか
  - MCQ / Cloze / Writing セクションが欠落していないか
  - /api/explain が十分な説明テキスト(text)を返すか
  - /api/grade が選択肢採点を正しく行うか
注意:
  提示された元仕様では /api/explain が 'explanation' キー、/api/grade が answer/expected を直接受ける形でしたが、
  現行コード(main.py)では /api/explain -> {'text': ...}, /api/grade -> GradeRequest(unit,tone,items[{'question','selected'}]) です。
  そのためテストを現行実装に合わせて調整しています。
"""

import pytest
from fastapi.testclient import TestClient
from quiz_pack.backend.main import app

client = TestClient(app)

UNITS = [str(i) for i in range(19, 26)]
TONES = ["standard", "osaka"]

@pytest.mark.parametrize("unit", UNITS)
@pytest.mark.parametrize("tone", TONES)
def test_quiz_endpoint(unit: str, tone: str):
    resp = client.post("/api/quiz", json={"unit": unit, "tone": tone})
    assert resp.status_code == 200, f"/api/quiz {unit} {tone} ステータス異常"
    data = resp.json()
    # 必須キー存在
    for key in ["explanation", "mcq", "cloze", "writing"]:
        assert key in data, f"{unit} {tone}: {key} 欠落"
    # 型チェック（最低限）
    assert isinstance(data["mcq"], list), "mcq は list であるべき"
    assert isinstance(data["cloze"], list), "cloze は list であるべき"
    assert isinstance(data["writing"], list), "writing は list であるべき"
    # MCQ アイテム構造チェック（可能な範囲）
    for item in data["mcq"]:
        assert "question" in item, "MCQ question 欠落"
        assert "choices" in item and isinstance(item["choices"], list) and item["choices"], "MCQ choices 不正"
        assert "answer" in item, "MCQ answer 欠落"
        # answer は choices に含まれること
        if isinstance(item["choices"], list) and item["choices"]:
            assert item["answer"] in item["choices"], "MCQ answer 不一致"

@pytest.mark.parametrize("unit", UNITS)
@pytest.mark.parametrize("tone", TONES)
def test_explain_endpoint(unit: str, tone: str):
    resp = client.post("/api/explain", json={"unit": unit, "tone": tone})
    assert resp.status_code == 200, f"/api/explain {unit} {tone} ステータス異常"
    data = resp.json()
    # 現行仕様: text キー
    text = data.get("text", "")
    assert isinstance(text, str) and len(text) > 30, f"{unit} {tone}: 説明文が短すぎる/欠落"

@pytest.mark.parametrize("unit", ["19"])  # 代表として文法19のみ詳細採点検証
@pytest.mark.parametrize("tone", ["standard"])  # トーン差による採点差は現行仕様では無い前提
def test_grade_endpoint(unit: str, tone: str):
    """/api/grade: 正解/不正解判定が期待通りか。
    手順:
      1. /api/quiz で MCQ を取得
      2. 最初のMCQを正解選択 -> isCorrect True
      3. 同じ質問を意図的に別選択 -> isCorrect False
    """
    quiz_resp = client.post("/api/quiz", json={"unit": unit, "tone": tone})
    assert quiz_resp.status_code == 200, "事前 /api/quiz 取得失敗"
    quiz_data = quiz_resp.json()
    mcq_list = quiz_data.get("mcq", [])
    assert mcq_list, "MCQ が空"
    first = mcq_list[0]
    question = first.get("question")
    answer = first.get("answer")
    choices = first.get("choices", [])
    assert question and answer and choices, "MCQ アイテム不完全"

    # 正解ケース
    payload_correct = {
        "unit": unit,
        "tone": tone,
        "items": [{"question": question, "selected": answer}]
    }
    grade_ok = client.post("/api/grade", json=payload_correct)
    assert grade_ok.status_code == 200, "/api/grade 正解ケース失敗"
    gdata_ok = grade_ok.json()
    assert gdata_ok.get("correct") == 1, "正解カウント不一致"
    assert gdata_ok.get("total") == 1, "total 不一致"
    assert gdata_ok.get("results")[0].get("isCorrect") is True, "isCorrect True 期待"

    # 不正解ケース（answer 以外の選択肢を選ぶ）
    wrong_choice = next((c for c in choices if c != answer), None)
    if wrong_choice is None:  # すべて同一など異常
        pytest.skip("適切な誤答選択肢が生成されていないためスキップ")
    payload_wrong = {
        "unit": unit,
        "tone": tone,
        "items": [{"question": question, "selected": wrong_choice}]
    }
    grade_ng = client.post("/api/grade", json=payload_wrong)
    assert grade_ng.status_code == 200, "/api/grade 誤答ケース失敗"
    gdata_ng = grade_ng.json()
    assert gdata_ng.get("correct") == 0, "誤答でも正解扱いになっている" 
    assert gdata_ng.get("results")[0].get("isCorrect") is False, "isCorrect False 期待"

def test_grade_stem_match():
    """語幹一致と部分一致の判定を judge.grade_answer で検証"""
    from quiz_pack.backend.judge import grade_answer
    assert grade_answer("닫고있어요", "닫고 있어요")["mode"] in ("語幹一致","完全一致")
    assert grade_answer("켜있다", "켜져있어요")["mode"] in ("部分一致","語幹一致")
    assert not grade_answer("문을 열어요", "문을 닫아요")["correct"]

if __name__ == "__main__":
    # 単体実行サポート
    import sys
    import pytest as _pytest
    sys.exit(_pytest.main([__file__, '-v']))
