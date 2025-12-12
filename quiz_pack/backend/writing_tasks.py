from typing import List, Dict
import json

def generate_writing_tasks_19_25() -> List[Dict]:
    """文法19〜25の作文問題リストを返す。"""
    return [
        {"unit": "19", "question": "いま韓国語を勉強しています。", "word_pool": ["공부하다", "한국어", "지금"]},
        {"unit": "20", "question": "ドアが閉まっています。", "word_pool": ["닫히다", "문", "있다"]},
        {"unit": "21", "question": "まだ手紙を送っていません。", "word_pool": ["아직", "편지", "보내다", "않다"]},
        {"unit": "22", "question": "先生は昼ご飯を召し上がっています。", "word_pool": ["점심", "선생님", "드시다", "계시다"]},
        {"unit": "23", "question": "水を飲みます。", "word_pool": ["물", "마시다"]},
        {"unit": "24", "question": "寒いけれども外に出かけます。", "word_pool": ["춥다", "나가다"]},
        {"unit": "25", "question": "一緒に映画を見ましょうか？", "word_pool": ["같이", "보다", "영화"]},
    ]


def tasks_for_unit(unit: str) -> List[Dict]:
    """指定ユニットの作文問題のみ抽出"""
    all_tasks = generate_writing_tasks_19_25()
    return [task for task in all_tasks if task["unit"] == str(unit)]


def to_writing_items(unit: str, explanation: str = "") -> List[Dict]:
    """既存API構造互換の辞書形式に変換"""
    tasks = tasks_for_unit(unit)
    items = []
    for t in tasks:
        items.append({
            "instruction": t["question"],
            "wordPool": t["word_pool"],
            "answer": "",
            "explanation": explanation
        })
    return items


if __name__ == "__main__":
    """単体テスト実行用（JSON表示）"""
    all_tasks = generate_writing_tasks_19_25()
    print(json.dumps(all_tasks, ensure_ascii=False, indent=2))
    print("---- Unit 22 ----")
    print(json.dumps(tasks_for_unit("22"), ensure_ascii=False, indent=2))
    print("---- To writing items ----")
    print(json.dumps(to_writing_items("19", "進行形 -고 있다 の練習です。"), ensure_ascii=False, indent=2))
