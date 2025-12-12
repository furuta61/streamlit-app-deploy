"""文法19～25 向けの問題生成（説明は rules.py に分離）。

各ユニット最小構成:
    MCQ: 2問
    Cloze: 1問
    Writing: 1問
未整備だった 19,22,25 を補完。
"""
from typing import List, Dict
import json
import os
# 相対インポートに変更
from .rules import rules

def generate_explanation(unit: str, tone: str = "standard") -> str:
    return rules.get(unit, {}).get(tone, "説明がまだ登録されていません。")

def generate_mcq(unit: str, tone: str = "standard") -> List[Dict]:
    """4択問題を生成。各アイテムに explanation フィールドを含める。"""
    exp = generate_explanation(unit, tone)
    if unit == "19":
        return [
            {
                "question": "次の中で、“今まさに閉めている最中”を正しく表している文はどれですか？",
                "choices": ["문이 닫혀 있어요", "문을 닫고 있어요", "문이 닫아 있어요", "문을 닫아 있어요"],
                "answer": "문을 닫고 있어요",
                "explanation": exp if tone == "standard" else "〜してる最中やで。終わってしもてる状態とはちゃうで！",
            },
            {
                "question": "次の中で、“座っている最中”を自然に表現しているのはどれですか？",
                "choices": ["할아버지가 앉아 있어요", "할아버지가 앉고 있어요", "할아버지가 앉혀 있어요", "할아버지가 앉혀요"],
                "answer": "할아버지가 앉고 있어요",
                "explanation": exp if tone == "standard" else "〜してる最中やで。終わってる状態やないで。",
            },
            {
                "question": "책을 읽고 있어요 の中心的ニュアンスは？",
                "choices": ["完了した状態", "進行中", "未来の予定", "習慣的動作"],
                "answer": "進行中",
                "explanation": exp,
            },
            {
                "question": "進行形を作る基本パターンは？",
                "choices": ["動詞語幹+고 있어요", "動詞語幹+아/어 있다", "動詞語幹+겠어요", "動詞語幹+고 싶어요"],
                "answer": "動詞語幹+고 있어요",
                "explanation": exp,
            },
        ]
    elif unit == "20":
        return [
            {
                "question": "次の中で、“ドアが閉まっている状態”を自然に表しているのはどれですか？",
                "choices": ["문을 닫고 있어요", "문이 닫혀 있어요", "문이 닫아 있어요", "문을 닫고 계세요"],
                "answer": "문이 닫혀 있어요",
                "explanation": exp if tone == "standard" else "終わってそのままの状態や。今やってる最中とはちゃうねん。",
            },
            {
                "question": "次の中で、“電気がついている状態”を表しているものはどれですか？",
                "choices": ["불이 켜고 있어요", "불이 켜져 있어요", "불을 켜고 있어요", "불을 켜고 계세요"],
                "answer": "불이 켜져 있어요",
                "explanation": exp if tone == "standard" else "終わってそのままの状態や。今やってる最中とはちゃうねん。",
            },
            {
                "question": "닫다 → ( ? )",
                "choices": ["가 있다", "닫혀 있다", "닫아요", "닫습니다"],
                "answer": "닫혀 있다",
                "explanation": exp,
            },
        ]
    elif unit == "21":
        return [
            {
                "question": "『まだ食事していない』自然な韓国語はどれ？",
                "choices": ["아직 식사 안 했어요", "식사 아직 했어요", "식사 아직 아니에요", "아직 식사 했지 않았어요"],
                "answer": "아직 식사 안 했어요",
                "explanation": exp,
            },
            {
                "question": "否定の二形：『아직 공부 안 했어요』と意味が近いものは？",
                "choices": ["아직 공부하지 않았어요", "아직 공부했지 않아요", "아직 공부 안 했지요", "공부 아직 했어요"],
                "answer": "아직 공부하지 않았어요",
                "explanation": exp,
            }
        ]
    elif unit == "22":
        # 特殊尊敬語にフォーカス（드시다/주무시다/잡수시다/계시다）
        return [
            {
                "question": "『食べる』の尊敬語として正しいものはどれ？",
                "choices": ["먹으시다", "먹다", "드시다", "드시어요"],
                "answer": "드시다",
                "explanation": (
                    "『드시다』が“食べる”の尊敬語やで。『먹다』にそのまま 시 はつけへんのや。"
                    if tone == "osaka" else exp
                ),
            },
            {
                "question": "『寝る』の尊敬語として正しいものはどれ？",
                "choices": ["자시다", "주무시다", "자세요", "쉬세요"],
                "answer": "주무시다",
                "explanation": (
                    "『주무시다』だけが特別な尊敬語やねん。『자다』は『자세요』になるけど尊敬語ではあらへん。"
                    if tone == "osaka" else exp
                ),
            },
            {
                "question": "『いる』の尊敬語はどれ？",
                "choices": ["있으시다", "있다", "계시다", "계세요"],
                "answer": "계시다",
                "explanation": (
                    "『계시다』が“いる”の尊敬やで。『있다』をそのまま尊敬にせぇへん。"
                    if tone == "osaka" else exp
                ),
            },
            {
                "question": "『召し上がる』のもう一つの言い方は？",
                "choices": ["드세요", "잡수시다", "먹으세요", "드시어요"],
                "answer": "잡수시다",
                "explanation": (
                    "『잡수시다』も“召し上がる”の尊敬語やねん。試験でも出るで。"
                    if tone == "osaka" else exp
                ),
            },
        ]
    elif unit == "23":
        return [
            {
                "question": "名詞＋요 の主なニュアンスは？",
                "choices": ["激しい命令", "過去を表す", "柔らかい丁寧な返答", "未来推測"],
                "answer": "柔らかい丁寧な返答",
                "explanation": exp,
            },
            {
                "question": "『요즘 일이 많아서요』はどんな場面でよく使う？",
                "choices": ["初対面自己紹介冒頭", "返答・理由を柔らかく示すとき", "強い否定を入れるとき", "激しい感情をぶつけるとき"],
                "answer": "返答・理由を柔らかく示すとき",
                "explanation": exp,
            }
        ]
    elif unit == "24":
        return [
            {
                "question": "『A기는 하지만 B』構文の機能は？",
                "choices": ["Aを完全否定", "AとBを並列", "Aを一部認めつつ B を述べる譲歩", "未来推測"],
                "answer": "Aを一部認めつつ B を述べる譲歩",
                "explanation": exp,
            },
            {
                "question": "맛있기는 하지만 비싸요 の日本語は？",
                "choices": ["おいしいし安いです", "おいしくないけど高いです", "おいしいけど高いです", "高いけどおいしくないです"],
                "answer": "おいしいけど高いです",
                "explanation": exp,
            }
        ]
    elif unit == "25":
        return [
            {
                "question": "같이 갈까요? の語尾 -까요? の機能は？",
                "choices": ["丁寧命令", "提案/勧誘", "過去推定", "条件仮定"],
                "answer": "提案/勧誘",
                "explanation": exp,
            },
            {
                "question": "-(으)ㄹ게요 の用法で最も近い説明は？",
                "choices": ["他者への依頼", "自分の意思・約束", "過去完了", "否定強調"],
                "answer": "自分の意思・約束",
                "explanation": exp,
            }
        ]
    return []

def generate_cloze(unit: str, tone: str = "standard") -> List[Dict]:
    """学習目標に沿った概念重視 Cloze を生成。
    改善点:
      - 単語一文字穴埋めから、文全体のターゲット構文を欠落させる形式へ
      - distractors: 似ているがニュアンス/形が異なる文法形
      - concept (学習目標要約) を付加
    返却各アイテムキー:
      question: 穴埋め文（____ 付き）
      answer: 正しい文法形（欠落部分）
      pattern: 対象パターン
      distractors: 誤用選択肢候補（UIで利用可能）
      concept: 学習目標サマリ
      explanation: 元ユニット説明
    """
    exp = generate_explanation(unit, tone)
    # 学習目標ロード
    concept = ""
    obj_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "learning_objectives.json")
    try:
        with open(obj_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        key = f"文法{unit}.docx"
        lines = data.get(key) or []
        if lines:
            # 最初の行を簡易サマリ抽出
            concept = lines[0].split("\n")[0].replace("学習目標", "").strip()
    except Exception:
        concept = ""

    # パターン & distractors 定義
    patterns = {
        "19": {"pattern": "-고 있다", "distractors": ["-아/어 있다", "現在形", "-겠-"]},
        "20": {"pattern": "-아/어 있다", "distractors": ["-고 있다", "-고 계시다", "-게 되다"]},
        "21": {"pattern": "아직 안 V 했어요", "distractors": ["아직 V 안 해요", "아직 V 하지 않아요", "안 아직 V 했어요"]},
        "22": {"pattern": "特殊尊敬語", "distractors": ["드시시다", "자시다", "있으시다"]},
        "23": {"pattern": "名詞/副詞+요", "distractors": ["名詞+이다", "名詞+입니다", "名詞+예요 (誤用文脈)"]},
        "24": {"pattern": "A기는 하지만 B", "distractors": ["A지만 B", "A하고 B", "A았지만 B"]},
        "25": {"pattern": "-(으)ㄹ게요", "distractors": ["-(으)까요?", "-겠어요", "-고 싶어요"]},
    }

    pinfo = patterns.get(unit)
    if not pinfo:
        return []

    pat = pinfo["pattern"]
    dist = pinfo["distractors"]

    items: List[Dict] = []

    def make(question_sentence: str, answer_fragment: str, original: str = ""):
        items.append({
            "question": question_sentence,
            "answer": answer_fragment,
            "pattern": pat,
            "distractors": dist,
            "concept": concept,
            "explanation": exp,
            "original": original or question_sentence.replace("____", answer_fragment),
        })

    if unit == "19":
        make("지금 책을 읽____ (現在進行で強調)", "고 있어요", "지금 책을 읽고 있어요")
        make("비가 오____ (雨が降っています)", "고 있어요", "비가 오고 있어요")
    elif unit == "20":
        make("문이 닫혀 ____ (ドアが閉まった状態)", "있어요", "문이 닫혀 있어요")
        make("불이 켜져 ____ (電気がついている状態)", "있어요", "불이 켜져 있어요")
    elif unit == "21":
        make("아직 식사 ____ 했어요 (まだ食事していません)", "안", "아직 식사 안 했어요")
        make("아직 결혼하지 ____ (まだ結婚していません 書き言葉)", "않았어요", "아직 결혼하지 않았어요")
    elif unit == "22":
        make("선생님께서 점심을 드시고 ____ (召し上がっている最中)", "계세요", "선생님께서 점심을 드시고 계세요")
        make("할아버지께서 방에서 ____ (お休みになっています)", "주무시고 계세요", "할아버지께서 방에서 주무시고 계세요")
    elif unit == "23":
        make("요즘 일이 많아서____ (柔らかい返答)", "요", "요즘 일이 많아서요")
        make("그 책이요 → この用法の 요 は ____ を省略した丁寧化", "이다", "그 책이다 → 省略+요")
    elif unit == "24":
        make("맛있기는 ____ 비싸요 (譲歩構文)", "하지만", "맛있기는 하지만 비싸요")
        make("예쁘기는 ____ 조금 멀어요 (譲歩構文)", "하지만", "예쁘기는 하지만 조금 멀어요")
    elif unit == "25":
        make("제가 도와드릴____ (私が手伝いますね)", "게요", "제가 도와드릴게요")
        make("같이 갈____? (一緒に行きましょうか？)", "까요", "같이 갈까요?")

    return items

def generate_writing(unit: str, tone: str = "standard") -> List[Dict]:
    exp = generate_explanation(unit, tone)
    if unit == "19":
        return [
            {
                "instruction": "『雨が降っています』を書いてください。",
                "answer": "비가 오고 있어요",
                "explanation": exp,
            },
            {
                "instruction": "『私は荷物を置いています。』を書いてください。",
                "answer": "짐을 놓고 있어요",
                "explanation": exp,
            },
        ]
    elif unit == "20":
        return [{
            "instruction": "“ドアが閉まった状態である”を韓国語で書いてください。",
            "answer": "문이 닫혀 있어요",
            "explanation": exp,
        }]
    elif unit == "21":
        return [{
            "instruction": "『まだ結婚していません』を二通り（会話的 / 書き言葉）で書いてください。",
            "answer": "아직 결혼 안 했어요 / 아직 결혼하지 않았어요",
            "explanation": exp,
        }]
    elif unit == "22":
        return [{
            "instruction": "『先生は昼ご飯を召し上がっています。』を書いてください。",
            "answer": "선생님께서 점심을 드시고 계세요",
            "explanation": exp,
        }]
    elif unit == "23":
        return [{
            "instruction": "理由を柔らかく丁寧に『最近仕事が多くて…』と書いてください。",
            "answer": "요즘 일이 많아서요",
            "explanation": exp,
        }]
    elif unit == "24":
        return [{
            "instruction": "『おいしいけど高いです』を譲歩構文で書いてください。",
            "answer": "맛있기는 하지만 비싸요",
            "explanation": exp,
        }]
    elif unit == "25":
        return [{
            "instruction": "『一緒に行きましょうか？』を韓国語で書いてください。",
            "answer": "같이 갈까요?",
            "explanation": exp,
        }]
    return []


def generate_concept_cloze(unit: str) -> List[Dict]:
    """学習目標ベースの概念確認用穴埋め（日本語メタ問題）。
    返却各アイテムキー:
      - question: 日本語の設問（カッコに語を入れる形式）
      - choices: 選択肢（語のリスト）
      - answer: 正答の配列（複数空欄に対応）
      - type: 固定で "concept"
      注意: tone に依らず文面は標準（日本語）のまま。
    """
    bank: Dict[str, List[Dict]] = {
        "19": [
            {
                "question": "「-(고) 있다」は動作の（　　　　）や（　　　　）を表す表現です。",
                "choices": ["進行", "習慣", "完了", "結果", "推測"],
                "answer": ["進行", "習慣"],
            }
        ],
        "20": [
            {
                "question": "「-아/어 있다」は（　　　　）した後の（　　　　）を表す。",
                "choices": ["進行", "完了", "状態", "推測", "意向"],
                "answer": ["完了", "状態"],
            }
        ],
        "21": [
            {
                "question": "『まだ〜していない』は会話では（　　　　）、書き言葉では（　　　　）を用いる。",
                "choices": ["안 V 했어요", "V하지 않았어요", "못 V 했어요", "V했지 않았어요"],
                "answer": ["안 V 했어요", "V하지 않았어요"],
            }
        ],
        "22": [
            {
                "question": "尊敬語：『食べる』→（　　　　）、『寝る』→（　　　　）、『いる』→（　　　　）。",
                "choices": ["드시다", "주무시다", "계시다", "잡수시다", "있으시다"],
                "answer": ["드시다", "주무시다", "계시다"],
            }
        ],
        "23": [
            {
                "question": "名詞＋요 は（　　　　）を柔らかく伝える/補う働きがある。",
                "choices": ["理由", "命令", "推量", "疑問", "未来"],
                "answer": ["理由"],
            }
        ],
        "24": [
            {
                "question": "『A기는 하지만 B』は A を（　　　　）しつつ B を述べる（　　　　）表現である。",
                "choices": ["全面否定", "一部認める", "譲歩", "並列", "対比"],
                "answer": ["一部認める", "譲歩"],
            }
        ],
        "25": [
            {
                "question": "-(으)ㄹ까요? は相手の（　　　　）を尋ねたり（　　　　）場面で用いる。3人称主語では（　　　　）を表す。",
                "choices": ["意見", "誘う", "推量", "命令", "願望"],
                "answer": ["意見", "誘う", "推量"],
            }
        ],
    }

    out = []
    for q in bank.get(unit, []):
        item = {
            "type": "concept",
            "question": q["question"],
            "choices": q.get("choices", []),
            "answer": q.get("answer", []),
        }
        out.append(item)
    return out
