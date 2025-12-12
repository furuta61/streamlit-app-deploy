# -*- coding: utf-8 -*-
"""judge.py
回答評価・品質判定関連。
"""
from __future__ import annotations
import re
from typing import Dict, List

def evaluate_document_relevance(query: str, document_text: str) -> float:
    query_lower = query.lower(); doc_lower = document_text.lower()
    query_keywords = re.findall(r'[가-힣]+|[ぁ-んァ-ン一-龯]+', query)
    if not query_keywords:
        return 0.5
    matches = sum(1 for kw in query_keywords if kw.lower() in doc_lower)
    keyword_ratio = matches / len(query_keywords)
    grammar_terms = ['語幹','활용','존경어','시','으시','불규칙','변화']
    grammar_matches = sum(1 for term in grammar_terms if term in doc_lower and term in query_lower)
    exclude_patterns = ['練習','問題','解答','완성','문제']
    penalty = sum(0.1 for p in exclude_patterns if p in doc_lower)
    final = (keyword_ratio*0.7 + grammar_matches*0.3) - penalty
    return max(0.0, min(1.0, final))

def evaluate_answer_quality(question: str, answer: str, sources: List[str]) -> Dict:
    score_accuracy = 4 if any(term in answer for term in ['특징','예','覚え方']) else 3
    score_completeness = 5 if len(answer) > 200 else 3
    score_clarity = 4 if any(term in answer for term in ['💡','🔹','例']) else 3
    score_consistency = 5 if sources else 3
    overall = (score_accuracy+score_completeness+score_clarity+score_consistency)/4
    return {
        'scores': {
            'accuracy': score_accuracy,
            'completeness': score_completeness,
            'clarity': score_clarity,
            'consistency': score_consistency
        },
        'overall_score': round(overall,1),
        'strengths': ['詳細な説明','構造化された内容'] if len(answer)>200 else ['簡潔な説明'],
        'weaknesses': ['より多くの例文が必要'] if len(answer)<300 else [],
        'improvement_suggestions': ['具体例を追加','練習問題を含める'],
        'is_satisfactory': overall >= 3.5
    }

def improve_answer_with_judge(original_answer: str, evaluation: Dict, question: str) -> str:
    if evaluation.get('is_satisfactory'):
        return original_answer
    parts = [original_answer, '\n\n## 🔧 補足説明']
    if '具体例を追加' in evaluation.get('improvement_suggestions', []):
        parts.append('📝 **追加ポイント:** もっと例文を増やし運用感覚を養いましょう')
    if '練習問題を含める' in evaluation.get('improvement_suggestions', []):
        parts.append('💪 **練習:** 韓国語→日本語、日本語→韓国語の双方向翻訳を作ってみる')
    return '\n'.join(parts)

def evaluate_translation_pair_quality(jp_text: str, kr_text: str, grammar_level: str) -> Dict:
    score = 4.2; issues: List[str] = []
    jp = (jp_text or '').strip(); kr = (kr_text or '').strip()
    if not re.search(r'(。|！|？)$|です$|ます$|ください$|でしょう$|ません$|たいです$|か[？\?]$', jp):
        score -= 0.8; issues.append('日本語終止形不自然')
    if not re.search(r'(다|요|죠|겠어요|ㅂ니다|습니까|세요|일까요|까요)[.。!?]?$', kr):
        score -= 0.8; issues.append('韓国語終止形不自然')
    if len(jp)<5 or len(kr)<3:
        score -= 0.8; issues.append('短すぎ')
    if len(jp)>120 or len(kr)>120:
        score -= 0.3; issues.append('長すぎ')
    final = max(1.0, min(5.0, score))
    return {'score': final, 'is_good_quality': final>=3.9, 'issues': issues, 'recommendation': '使用推奨' if final>=3.9 else '要注意'}

__all__ = [
    'evaluate_document_relevance','evaluate_answer_quality','improve_answer_with_judge',
    'evaluate_translation_pair_quality'
]
