import streamlit as st
import docx
import os
import re
import random

WORD_DIR = os.path.join(os.path.dirname(__file__), "word_files")

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


# ─── クイズ生成（받침カウント — 翻訳クイズが足りない場合のフォールバック）

def count_batchim(texts, batchim_idx):
    count = 0
    for text in texts:
        for c in text:
            if "가" <= c <= "힣":
                if (ord(c) - 0xAC00) % 28 == batchim_idx:
                    count += 1
    return count


def generate_counting_quiz(korean_texts, seed):
    if not korean_texts:
        return []
    rng = random.Random(seed + 1000)
    candidates = list(BATCHIM.items())   # [(idx, char), ...]
    rng.shuffle(candidates)

    questions = []
    for batchim_idx, batchim_char in candidates:
        count = count_batchim(korean_texts, batchim_idx)
        if count < 2:
            continue
        spread = [max(0, count - 1), count, count + 1, count + 2]
        opts = sorted(set(spread))[:4]
        while len(opts) < 4:
            opts.append(opts[-1] + 1)
        rng.shuffle(opts)
        questions.append({
            "question": f"例文中に「{batchim_char}」の받침（パッチム）を持つ文字はいくつある？",
            "options":  [f"{n}個" for n in opts],
            "answer":   f"{count}個",
            "explain":  f"「{batchim_char}」の받침を持つ文字は{count}個あります。",
        })
        if len(questions) == 2:
            break

    return questions


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

    # チャット
    if content["dialogues"]:
        st.markdown(build_chat_html(content["dialogues"]), unsafe_allow_html=True)

    # クイズ（翻訳 → 不足時はカウント形式）
    questions = generate_translation_quiz(content["examples"], seed=selected_num)
    if not questions:
        questions = generate_counting_quiz(content["korean_texts"], seed=selected_num)

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

    # 練習問題
    if content["basic"] or content["applied"]:
        with st.expander("📝 練習問題"):
            if content["basic"]:
                st.markdown("**基本練習**")
                for line in content["basic"]:
                    st.write(line)
            if content["applied"]:
                st.markdown("**応用問題**")
                for line in content["applied"]:
                    st.write(line)


if __name__ == "__main__":
    main()
