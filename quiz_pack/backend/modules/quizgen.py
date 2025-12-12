# -*- coding: utf-8 -*-
"""quizgen.py
問題生成ロジック (MCQ / Cloze / Writing) を集約。
"""
from __future__ import annotations
from typing import List, Dict
import random

# シンプルなスタブ。必要に応じて元の quiz_generator から詳細ロジックを移植。

COMMON_DISTRACTORS = ['-고 있다','-아/어 있다','-(으)시-','-겠-','-었-','-ㄹ 것이다']

EXAMPLES = {
    '文法19': {
        'pattern': '-고 있다',
        'jp': '今勉強しています。',
        'kr': '지금 공부하고 있어요.'
    },
    '文法20': {
        'pattern': '-아/어 있다',
        'jp': 'ドアが開いています。',
        'kr': '문이 열려 있어요.'
    },
    '文法21': {
        'pattern': '-(으)시-',
        'jp': '先生は今お休みになっています。',
        'kr': '선생님께서는 지금 쉬고 계세요.'
    },
}


def make_mcq(grammar_key: str) -> Dict:
    base = EXAMPLES.get(grammar_key)
    if not base:
        # fallback: pick any key
        grammar_key = random.choice(list(EXAMPLES.keys()))
        base = EXAMPLES[grammar_key]
    correct = base['pattern']
    distractors = [d for d in COMMON_DISTRACTORS if d != correct]
    random.shuffle(distractors)
    options = [correct] + distractors[:3]
    random.shuffle(options)
    return {
        'type': 'mcq',
        'grammar_key': grammar_key,
        'question': f"次の日本語を韓国語にする際に最も適切な文法表現はどれですか？『{base['jp']}』",
        'source_jp': base['jp'],
        'source_kr': base['kr'],
        'options': options,
        'answer': correct
    }


def make_cloze(grammar_key: str) -> Dict:
    mcq = make_mcq(grammar_key)
    kr = mcq['source_kr']
    pattern = mcq['answer']
    masked = kr.replace(pattern.replace(' 있다',' 있어요').split()[0], '____') if pattern in kr else kr.replace(pattern, '____')
    return {
        'type': 'cloze',
        'grammar_key': grammar_key,
        'sentence_masked': masked,
        'answer': pattern,
        'original': kr
    }


def make_writing(grammar_key: str) -> Dict:
    ex = EXAMPLES.get(grammar_key) or random.choice(list(EXAMPLES.values()))
    return {
        'type': 'writing',
        'prompt': f"『{ex['jp']}』を学習中の文法を明確に使って韓国語で書いてください。 ({grammar_key})",
        'expected_focus': ex['pattern']
    }


def generate_quiz_set(target_keys: List[str], include_types: List[str] = None, n_per_key: int = 3) -> List[Dict]:
    include_types = include_types or ['mcq','cloze','writing']
    result: List[Dict] = []
    for key in target_keys:
        for _ in range(n_per_key):
            if 'mcq' in include_types:
                result.append(make_mcq(key))
            if 'cloze' in include_types:
                result.append(make_cloze(key))
            if 'writing' in include_types:
                result.append(make_writing(key))
    random.shuffle(result)
    return result

__all__ = [
    'make_mcq','make_cloze','make_writing','generate_quiz_set'
]
