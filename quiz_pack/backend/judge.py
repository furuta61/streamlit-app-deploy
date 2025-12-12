# -- coding: utf-8 --
"""
採点モジュール: 語幹一致・部分一致を含む判定 (教育用途)
"""
import re
import unicodedata

__all__ = ["grade_answer", "normalize_hangul", "compare_stems"]

def normalize_hangul(text: str) -> str:
    """ハングル・日本語・スペースを正規化し比較容易化"""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    # スペース・句読点など最低限除去（必要なら拡張）
    text = re.sub(r"\s+", "", text)
    return text.strip()

def compare_stems(user: str, expected: str) -> bool:
    """語幹一致判定: 닫다 / 닫아요 / 닫고 있어요 / 닫혀있어요 → 닫 でそろえて比較
    改良点:
      - 受動/結果補助 '져','혀' などを除去
      - 進行/結果構文 '고있','어있','아있' を統一的に処理
      - 終止形 '다','요','습니다' 系や 丁寧過去 '었','았' を除去
    """
    u = normalize_hangul(user)
    e = normalize_hangul(expected)
    # 共通前処理: パターンを順序適用
    def stem_reduce(s: str) -> str:
        # 進行/結果 '고있다','고있어요','어있다','아있다' 等 → 活用部分削除
        s = re.sub(r"(고있[어요다]*)", "", s)
        s = re.sub(r"([어아]있[어요다]*)", "", s)
        # 単独存在補助 '있다','있어요' パターン除去 (켜있다/켜져있어요 → 켜)
        s = re.sub(r"있[어요다]*", "", s)
        # 受動/結果 '져','혀','려','워' などを1音節化（単純削除）
        s = re.sub(r"(져|혀|려|워)", "", s)
        # 終止・敬語・過去語尾など
        s = re.sub(r"(었습니다|았습니다|였어요|었어요|었습니?다|았습니?다|겠어요|겠습니까|겠습니?다)$", "", s)
        s = re.sub(r"(었|았|겠)$", "", s)
        s = re.sub(r"(습니다|습니까|요|다)$", "", s)
        return s
    u_red = stem_reduce(u)
    e_red = stem_reduce(e)
    return u_red == e_red and u_red != ""

def grade_answer(user_answer: str, correct_answer: str) -> dict:
    """拡張採点: 完全一致→語幹一致→部分一致→不一致 の順で評価
    戻り値: {correct: bool, score: float, mode: str}
    """
    user_norm = normalize_hangul(user_answer)
    correct_norm = normalize_hangul(correct_answer)

    if not user_norm and correct_norm:
        return {"correct": False, "score": 0.0, "mode": "空"}

    # 完全一致
    if user_norm == correct_norm:
        return {"correct": True, "score": 1.0, "mode": "完全一致"}

    # 語幹一致
    if compare_stems(user_norm, correct_norm):
        return {"correct": True, "score": 0.9, "mode": "語幹一致"}

    # 部分一致: 動詞コア抽出後で包含判定（名詞目的語の共有だけでは一致扱いしない）
    def core(s: str) -> str:
        # 目的語 + 助詞を除去: '문을열어요' -> '열어요'
        s2 = re.sub(r"^.*?[을를이가은는에게에서로]\s*", "", s)
        return s2
    core_user = core(user_norm)
    core_correct = core(correct_norm)
    if core_user and core_correct and (
        core_correct in core_user or core_user in core_correct
    ):
        return {"correct": True, "score": 0.7, "mode": "部分一致"}

    return {"correct": False, "score": 0.0, "mode": "不一致"}
