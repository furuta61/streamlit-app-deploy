# quiz_templates.py

def concept_question(unit: int, goal: str):
    return {
        "type": "concept",
        "question": f"次の文法{unit}の学習目標の空欄に入る最も適切な語を選びなさい。\n\n{goal.replace('～', '____')}",
        "choices": [],
        "answer": None
    }


def choice_question(sentence_kr, choices, answer):
    return {
        "type": "choice",
        "question": sentence_kr,
        "choices": choices,
        "answer": answer
    }


def writing_question(jp):
    return {
        "type": "writing",
        "question": jp,
        "answer_example": None
    }
