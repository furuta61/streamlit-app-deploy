import streamlit as st
import docx
import os
import re
import random

WORD_DIR = os.path.join(os.path.dirname(__file__), "word_files")

# 大阪弁バージョン（単元番号→内容）
OSAKA_RULES = {
    "12": {
        "standard": "### 📘 第12課：〜してあげる／くれる (-아/어 주다)\n相手のために何かをする親切の表現です。",
        "osaka": "### 🐙 第12課：〜したるわ／してくれへん？\n相手のために動くときの優しい表現やで。",
        "advanced": "東京外大モジュールでは、日本語の「〜してもらう」に相当する独自の文法が韓国語にはない点を指摘しています。",
    },
    "13": {"standard": "### 📘 第13課：〜すれば／なら (-면/으면)", "osaka": "### 🐙 第13課：〜やったら／すれば"},
    "14": {"standard": "### 📘 第14課：〜しましょうか／でしょうか (-ㄹ까요/을까요?)", "osaka": "### 🐙 第14課：〜しよか？／〜やろか？"},
    "15": {"standard": "### 📘 第15課：〜でしょう？ (-지요/죠)", "osaka": "### 🐙 第15課：〜やんな？／〜やろ？"},
    "16": {"standard": "### 📘 第16課：〜しましょう (-ㅂ시다/읍시다)", "osaka": "### 🐙 第16課：〜しよや！"},
    "17": {"standard": "### 📘 第17課：〜するつもり／だろう (-겠)", "osaka": "### 🐙 第17課：〜するわ／〜やろなぁ"},
    "18": {"standard": "### 📘 第18課：〜しに（行く・来る） (-러/으러)", "osaka": "### 🐙 第18課：〜しに（行くんや）"},
    "19": {"standard": "### 📘 第19課：〜している（進行・習慣） (-고 있다)", "osaka": "### 🐙 第19課：〜してんねん！"},
    "20": {"standard": "### 📘 第20課：〜している（結果の状態） (-아/어 있다)", "osaka": "### 🐙 第20課：〜しとる状態や"},
    "21": {"standard": "### 📘 第21課：否定 (안 / -지 않다)", "osaka": "### 🐙 第21課：〜せえへん"},
    "22": {"standard": "### 📘 第22課：尊敬 (-(으)시-)", "osaka": "### 🐙 第22課：〜してはる"},
    "23": {"standard": "### 📘 第23課：名詞＋(이)요", "osaka": "### 🐙 第23課：〜やで／〜ですよ"},
    "24": {"standard": "### 📘 第24課：〜ではあるけれど (-기는 하지만)", "osaka": "### 🐙 第24課：〜やけども"},
    "25": {"standard": "### 📘 第25課：意志・約束 (-ㄹ게요)", "osaka": "### 🐙 第25課：〜するわ！"},
}

BADGE = ["①","②","③","④","⑤","⑥","⑦","⑧","⑨","⑩","⑪","⑫"]

# 받침インデックス→文字
BATCHIM = {1:"ㄱ",4:"ㄴ",8:"ㄹ",16:"ㅁ",17:"ㅂ",19:"ㅅ",21:"ㅇ",27:"ㅎ"}

CUSTOM_CSS = """
<style>
.stApp {
    background-color: #fafafa;
}
.chat-container {
    background-color: #71C276;
    padding: 30px 20px;
    border-radius: 15px;
    margin-bottom: 30px;
    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    overflow: hidden;
}
.bubble {
    padding: 12px 18px;
    border-radius: 20px;
    margin-bottom: 15px;
    font-family: 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif;
    font-size: 18px;
    font-weight: 500;
    line-height: 1.5;
    max-width: 75%;
    position: relative;
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}
.bubble-a {
    background-color: #ffffff;
    color: #333333;
    float: right;
    border-bottom-right-radius: 2px;
}
.bubble-b {
    background-color: #ffffff;
    color: #333333;
    float: left;
    border-bottom-left-radius: 2px;
}
.speaker-name {
    font-size: 12px;
    color: #ffffff;
    font-weight: bold;
    margin-bottom: 4px;
    display: block;
}
.speaker-right { text-align: right; }
.speaker-left  { text-align: left; }
.clear { clear: both; margin-bottom: 10px; }
.badge {
    display: inline-block;
    background-color: #ffffff;
    color: #71C276;
    border-radius: 50%;
    width: 20px;
    height: 20px;
    text-align: center;
    line-height: 20px;
    font-size: 12px;
    margin-right: 5px;
    border: 1px solid #71C276;
}
.quiz-box {
    background-color: #ffffff;
    padding: 25px;
    border-radius: 12px;
    border-left: 5px solid #71C276;
    box-shadow: 0 2px 8px rgba(0,0,0,0.05);
    margin-bottom: 20px;
}
</style>
"""


# ─── ファイル一覧 ──────────────────────────────────────────────────

def get_chapters():
    if not os.path.exists(WORD_DIR):
        return []
    files = []
    for f in os.listdir(WORD_DIR):
        if not f.endswith(".docx") or not f.startswith("文法") or f.startswith("~$"):
            continue
        n = f.replace("文法", "").replace(".docx", "")
        n = n.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
        try:
            files.append((int(n), os.path.join(WORD_DIR, f)))
        except ValueError:
            pass
    return sorted(files)


# ─── 韓国語 / 日本語 分割 ─────────────────────────────────────────

def split_ko_jp(text):
    """
    1行から (韓国語部分, 日本語部分) を返す。
    対応形式:
      ① Korean   Japanese       （3文字以上スペース区切り）
      ② Korean（Japanese）       （全角括弧）
      ③ Korean (Japanese)        （半角括弧）
      ④ Korean。Japanese          （ひらがな/カタカナで境界検出）
    """
    # ① 3文字以上スペース
    parts = re.split(r"[ \t　]{3,}", text)
    if len(parts) >= 2 and re.search(r"[가-힣]", parts[0]):
        return parts[0].strip(), " ".join(parts[1:]).strip()

    # ② 全角括弧  Korean（Japanese）
    m = re.match(r"^(.+?)（(.+)）\s*$", text)
    if m and re.search(r"[가-힣]", m.group(1)):
        return m.group(1).strip(), m.group(2).strip()

    # ③ 半角括弧  Korean (Japanese)
    m = re.match(r"^(.+?)\((.+)\)\s*$", text)
    if m and re.search(r"[가-힣]", m.group(1)):
        return m.group(1).strip(), m.group(2).strip()

    # ④ ひらがな/カタカナ初出位置で分割
    m = re.search(r"[ぁ-んァ-ン]", text)
    if m:
        pos = m.start()
        split_at = -1
        for ch in (" ", "　", ".", "。", "?", "？", "!", "！"):
            idx = text.rfind(ch, 0, pos)
            if idx > split_at:
                split_at = idx
        if split_at > 0:
            return text[: split_at + 1].strip(), text[split_at + 1 :].strip()
        return text[:pos].strip(), text[pos:].strip()

    return text.strip(), ""


# ─── Wordパーサー ─────────────────────────────────────────────────

_DIALOGUE_RE = re.compile(
    r"(?:【[^】]*】\s*)?([ＡＢＣＤabcdABCD])[：:]\s*(.+)"
)


def parse_chapter(filepath):
    doc = docx.Document(filepath)
    paras = [p.text.strip() for p in doc.paragraphs if p.text.strip()]

    result = {
        "title": "",
        "subtitle": "",
        "learning_goal": "",
        "grammar": [],     # 文法説明テキスト（表示用）
        "dialogues": [],   # A:/B: 対話行（チャット表示）
        "examples": [],    # Korean+JP ペア（翻訳クイズ用）
        "korean_texts": [], # Korean テキスト集（カウントクイズ用）
        "basic": [],
        "applied": [],
    }
    subtitle_lines = []

    section = "intro"
    title_done = False

    for text in paras:
        if re.match(r"^\d+頁?$", text) or re.match(r"^\d+$", text):
            continue

        if re.match(r"^文法[１-９\d]", text) and not title_done:
            result["title"] = text
            title_done = True
            section = "intro"
            continue

        if "学習目標" in text:
            # intros区間のサブタイトルを結合してsubtitleに保存
            result["subtitle"] = "　".join(subtitle_lines)
            result["learning_goal"] = (
                text.replace("学習目標", "").strip().lstrip("　 ").strip()
            )
            section = "grammar"
            continue

        if re.match(r"^基本練習", text):
            section = "basic"
            continue
        if re.match(r"^応用(問題|練習)", text):
            section = "applied"
            continue

        if section == "grammar":
            dm = _DIALOGUE_RE.match(text)
            if dm:
                sp = dm.group(1).translate(str.maketrans("ＡＢＣＤabcd", "ABCDabcd")).upper()
                ko, jp = split_ko_jp(dm.group(2).strip())
                result["dialogues"].append({"speaker": sp, "korean": ko, "japanese": jp})
                result["korean_texts"].append(ko)
                if jp:
                    result["examples"].append({"korean": ko, "japanese": jp})
            else:
                result["grammar"].append(text)
                # 【ラベル】プレフィックスを除去してから分割（ラベル内のひらがなが誤検知の原因になるため）
                clean = re.sub(r"^【[^】]*】[　\s]*", "", text)
                if re.search(r"[가-힣]", clean):
                    ko, jp = split_ko_jp(clean)
                    if re.search(r"[가-힣]", ko):
                        result["korean_texts"].append(ko)
                        if jp:
                            result["examples"].append({"korean": ko, "japanese": jp})

        elif section == "basic":
            result["basic"].append(text)
        elif section == "applied":
            result["applied"].append(text)
        elif section == "intro" and title_done and not result["learning_goal"]:
            subtitle_lines.append(text)

    return result


# ─── チャット HTML ────────────────────────────────────────────────

def build_chat_html(dialogues):
    html = '<div class="chat-container">'
    for i, d in enumerate(dialogues):
        badge = BADGE[i] if i < len(BADGE) else str(i + 1)
        ko = d["korean"]
        sp = d["speaker"]
        if sp == "A":
            html += (
                f'<span class="speaker-name speaker-right">Ａ</span>'
                f'<div class="bubble bubble-a">'
                f'<span class="badge">{badge}</span>{ko}</div>'
                f'<div class="clear"></div>'
            )
        else:
            label = {"B": "Ｂ", "C": "Ｃ", "D": "Ｄ"}.get(sp, sp)
            html += (
                f'<span class="speaker-name speaker-left">{label}</span>'
                f'<div class="bubble bubble-b">'
                f'<span class="badge">{badge}</span>{ko}</div>'
                f'<div class="clear"></div>'
            )
    html += "</div>"
    return html


# ─── クイズ生成（翻訳） ───────────────────────────────────────────

def generate_translation_quiz(examples, seed):
    pool = [e for e in examples if e.get("japanese") and re.search(r"[가-힣]", e.get("korean", ""))]
    if len(pool) < 4:
        return []

    rng = random.Random(seed)
    picked = rng.sample(pool, min(2, len(pool)))
    questions = []

    # Q1: 韓 → 日
    q1 = picked[0]
    dis1 = [e["japanese"] for e in pool if e["japanese"] != q1["japanese"]]
    if len(dis1) >= 3:
        opts1 = [q1["japanese"]] + rng.sample(dis1, 3)
        rng.shuffle(opts1)
        questions.append({
            "question": f"「{q1['korean']}」の意味は？",
            "options":  opts1,
            "answer":   q1["japanese"],
            "explain":  f"「{q1['korean']}」は「{q1['japanese']}」という意味です。",
        })

    # Q2: 日 → 韓
    if len(picked) >= 2:
        q2 = picked[1]
        dis2 = [e["korean"] for e in pool if e["korean"] != q2["korean"]]
        if len(dis2) >= 3:
            opts2 = [q2["korean"]] + rng.sample(dis2, 3)
            rng.shuffle(opts2)
            questions.append({
                "question": f"「{q2['japanese']}」を韓国語にすると？",
                "options":  opts2,
                "answer":   q2["korean"],
                "explain":  f"「{q2['japanese']}」は韓国語で「{q2['korean']}」です。",
            })

    return questions


# ─── 穴埋め問題生成（学習目標の文法パターンを空欄に） ────────────

def extract_key_patterns(text):
    """テキストから韓国語の文法形式を抽出（2文字以上）"""
    return [t for t in re.findall(r"[가-힣]+", text) if len(t) >= 2]


def generate_cloze_quiz(content, seed):
    rng = random.Random(seed + 3000)

    # サブタイトル → 学習目標の順でパターンを探す
    patterns = extract_key_patterns(content.get("subtitle", ""))
    if not patterns:
        patterns = extract_key_patterns(content.get("learning_goal", ""))
    if not patterns:
        for g in content.get("grammar", []):
            patterns = extract_key_patterns(g)
            if patterns:
                break
    if not patterns:
        return []

    patterns_sorted = sorted(set(patterns), key=len, reverse=True)

    # 例文・対話から候補文を集める
    all_sentences = []
    for e in content.get("examples", []):
        all_sentences.append({"korean": e["korean"], "japanese": e.get("japanese", "")})
    for d in content.get("dialogues", []):
        if d.get("japanese"):
            all_sentences.append({"korean": d["korean"], "japanese": d["japanese"]})

    candidates = []
    used_answers = set()
    for item in all_sentences:
        ko = item["korean"]
        jp = item.get("japanese", "")
        if not ko or not jp:
            continue
        for pat in patterns_sorted:
            if pat in ko and pat not in used_answers:
                blanked = ko.replace(pat, "____", 1)
                if blanked != ko:
                    candidates.append({
                        "question": blanked,
                        "answer": pat,
                        "original": ko,
                        "hint": jp,
                    })
                    used_answers.add(pat)
                    break
        if len(candidates) >= 4:
            break

    if not candidates:
        return []

    return rng.sample(candidates, min(2, len(candidates)))


# ─── メイン ──────────────────────────────────────────────────────

def main():
    st.set_page_config(page_title="韓国語文法クイズ", layout="centered", page_icon="🇰🇷")
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

    chapters = get_chapters()
    if not chapters:
        st.error("word_files/ フォルダにWordファイルが見つかりません。")
        return

    with st.sidebar:
        st.markdown("## 🇰🇷 韓国語文法")
        st.markdown("---")
        labels = [f"第{num}課" for num, _ in chapters]
        selected_label = st.selectbox("章を選んでください", labels, index=0)
        idx = labels.index(selected_label)
        selected_num, selected_path = chapters[idx]
        st.markdown("---")
        tone = st.radio("🗣 バージョン", ["standard", "osaka"], horizontal=True)
        st.markdown("---")
        st.caption(f"全 {len(chapters)} 課")

    content = parse_chapter(selected_path)

    # ヘッダー
    st.title(content["title"] or f"第{selected_num}課")
    if content["subtitle"]:
        st.subheader(content["subtitle"])
    if content["learning_goal"]:
        st.write(content["learning_goal"])

    # 文法説明
    if content["grammar"]:
        with st.expander("📖 文法説明を見る", expanded=True):
            for line in content["grammar"]:
                st.write(line)

    # 大阪弁補足説明
    unit_key = str(selected_num)
    if unit_key in OSAKA_RULES:
        rule = OSAKA_RULES[unit_key]
        if tone == "osaka" and rule.get("osaka"):
            with st.expander("🐙 大阪弁バージョン", expanded=True):
                st.markdown(rule["osaka"])
        if rule.get("advanced"):
            with st.expander("💡 発展解説（東京外国語大学 朝鮮語文法モジュール参考）"):
                st.markdown(rule["advanced"])
    else:
        with st.expander("💡 発展解説（国立国語院・東京外国語大学 参考）"):
            st.markdown(
                "国立国語院（한국어문법 통합자료）および"
                "東京外国語大学『朝鮮語文法モジュール』を参考に、"
                "使い分けや補足情報を提供しています。"
            )

    # チャット
    if content["dialogues"]:
        st.markdown(build_chat_html(content["dialogues"]), unsafe_allow_html=True)

    # クイズ（翻訳のみ）
    questions = generate_translation_quiz(content["examples"], seed=selected_num)

    if questions:
        st.markdown("### 📝 Work")
        st.markdown('<div class="quiz-box">', unsafe_allow_html=True)

        user_answers = []
        for i, q in enumerate(questions):
            st.write(f"**{BADGE[i]} {q['question']}**")
            ans = st.radio(
                "選択してください",
                q["options"],
                key=f"q{selected_num}_{i}",
                index=None,
            )
            user_answers.append(ans)
            st.write("")

        if st.button("答え合わせをする", key=f"check_{selected_num}"):
            st.markdown("---")
            for i, (q, ans) in enumerate(zip(questions, user_answers)):
                if ans is None:
                    st.warning(f"{BADGE[i]} 未選択です。")
                elif ans == q["answer"]:
                    st.success(f"{BADGE[i]} 正解！ {q['explain']}")
                else:
                    st.error(f"{BADGE[i]} 不正解... 正解は「{q['answer']}」です。")

        st.markdown("</div>", unsafe_allow_html=True)

    # 穴埋め問題
    cloze_qs = generate_cloze_quiz(content, seed=selected_num)
    if cloze_qs:
        st.markdown("### ✏️ 穴埋め問題")
        st.caption("____に入る言葉を入力して「答えを見る」を押してください。")
        for i, q in enumerate(cloze_qs):
            st.write(f"**{BADGE[i]} 「{q['question']}」**")
            if q.get("hint"):
                st.caption(f"意味：{q['hint']}")
            user_input = st.text_input(
                "答えを入力：",
                key=f"cloze_{selected_num}_{i}",
                placeholder=f"例）{q['answer'][0]}..."
            )
            if st.button("答えを見る", key=f"cloze_btn_{selected_num}_{i}"):
                if user_input.strip() == q["answer"]:
                    st.success(f"✅ 正解！　→　{q['original']}")
                elif user_input.strip():
                    st.error(f"❌ 正解は「{q['answer']}」　→　{q['original']}")
                else:
                    st.info(f"💡 正解：「{q['answer']}」　→　{q['original']}")
            st.write("")

    # セリフ解説
    if content["dialogues"]:
        with st.expander("💡 セリフの解説を見る"):
            for i, d in enumerate(content["dialogues"]):
                badge = BADGE[i] if i < len(BADGE) else str(i + 1)
                jp = d.get("japanese", "")
                line = f"{badge} **{d['korean']}**"
                if jp:
                    line += f"　：　{jp}"
                st.write(line)

    # 作文・練習問題（Wordファイルの内容をそのまま表示）
    if content["basic"] or content["applied"]:
        with st.expander("📝 作文・練習問題"):
            if content["basic"]:
                st.markdown("**基本練習**")
                for j, line in enumerate(content["basic"]):
                    st.write(line)
                    # 問題行（番号・記号で始まる行）には解答欄を設ける
                    if re.match(r"^[\d①②③④⑤⑥⑦⑧⑨⑩（(]", line):
                        st.text_area(
                            "解答：",
                            key=f"basic_{selected_num}_{j}",
                            height=60,
                            label_visibility="collapsed",
                        )
            if content["applied"]:
                st.markdown("**応用問題**")
                for j, line in enumerate(content["applied"]):
                    st.write(line)
                    if re.match(r"^[\d①②③④⑤⑥⑦⑧⑨⑩（(]", line):
                        st.text_area(
                            "解答：",
                            key=f"applied_{selected_num}_{j}",
                            height=60,
                            label_visibility="collapsed",
                        )


if __name__ == "__main__":
    main()
