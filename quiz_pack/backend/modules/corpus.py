# -*- coding: utf-8 -*-
"""corpus.py
教材コーパス構築・DOCX読込・インデックス生成まわりを分離。
依存: python-docx, sentence_transformers, faiss (任意)
"""
from __future__ import annotations
import os
import re
import json
from pathlib import Path
from typing import List, Dict, Tuple, Optional

try:
    from docx import Document  # python-docx
except ImportError:
    Document = None  # type: ignore

import numpy as np
try:
    import faiss  # type: ignore
except Exception:
    faiss = None  # type: ignore
from sentence_transformers import SentenceTransformer  # type: ignore

# ===== 正規化ユーティリティ =====
_full_to_half = str.maketrans('０１２３４５６７８９', '0123456789')

def _normalize_digits(s: str) -> str:
    return s.translate(_full_to_half)

# ===== 文法キー抽出 =====
GRAMMAR_KEY_HINTS: Dict[str, str] = {
    "文法9": "아서 어서 고 차이 연결어미",
    "文法14": "(으)ㄹ까요 推量 提案 의문",
    "文法15": "지요 죠 よね でしょう",
}

JP_RE = re.compile(r"[ぁ-んァ-ン一-龯]")
KR_RE = re.compile(r"[가-힣]")

# ===== DOCX 読込 =====

def extract_grammar_key(text_or_name: str) -> Optional[str]:
    m = re.search(r"文法\s*([0-9０-９]+)", text_or_name)
    if m:
        return f"文法{int(_normalize_digits(m.group(1)))}"
    m2 = re.search(r"문법([0-9０-９]+)", text_or_name)
    if m2:
        return f"文法{int(_normalize_digits(m2.group(1)))}"
    return None

def _load_manual_grammar_map(base_dir: Path) -> Dict[str, str]:
    candidates = [
        base_dir / "config" / "grammar_page_map.json",
        base_dir / "grammar_page_map.json",
    ]
    for fp in candidates:
        try:
            if fp.is_file():
                with open(fp, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return {str(k): str(v) for k, v in data.items()}
        except Exception:
            continue
    return {}

def _apply_manual_grammar_map(docs: List[Dict], manual: Dict[str, str]) -> None:
    if not docs or not manual:
        return
    for d in docs:
        try:
            key = f"{d.get('source')}:{int(d.get('page') or 0)}"
            if key in manual:
                d["grammar_key"] = manual[key]
        except Exception:
            continue

def _propagate_grammar_keys_by_filename(docs: List[Dict]) -> None:
    try:
        from collections import defaultdict
        by_src = defaultdict(list)
        for d in docs:
            by_src[d.get("source")].append(d)
        for src, pages in by_src.items():
            gk_from_name = extract_grammar_key(src or "")
            if gk_from_name:
                for d in pages:
                    d["grammar_key"] = d.get("grammar_key") or gk_from_name
            last = None
            for d in sorted(pages, key=lambda x: int(x.get("page") or 0)):
                if d.get("grammar_key"):
                    last = d["grammar_key"]
                elif last:
                    d["grammar_key"] = last
    except Exception:
        pass

def _detect_audience_and_topics(text: str, source: str = "") -> Tuple[str, List[str]]:
    joined = f"{source}\n{text}"
    if any(k in joined for k in ["小学生", "초등", "児童"]):
        audience = "elementary"
    else:
        audience = "general"
    topics: List[str] = []
    if "ㄹ語幹" in joined or "ㄹ 탈락" in joined:
        topics.append("ㄹ語幹")
    if "해요체" in joined or "해요体" in joined:
        topics.append("해요体")
    if any(k in joined for k in ["(아/어)서", "아서", "어서", "-고", "연결어미"]):
        topics.append("서_고_連結")
    return audience, sorted(set(topics))

PLUS_ALPHA_TRIGGERS = ["+α", "＋α", "プラスアルファ"]

def _detect_plus_alpha(text: str) -> bool:
    return any(t in (text or "") for t in PLUS_ALPHA_TRIGGERS)

def _extract_plus_alpha_block(text: str) -> Optional[str]:
    if not text:
        return None
    lines = [l.rstrip() for l in text.splitlines()]
    start = None
    for i, l in enumerate(lines):
        if any(t in l for t in PLUS_ALPHA_TRIGGERS):
            start = i
            break
    if start is None:
        return None
    collected = []
    for j in range(start, min(len(lines), start + 60)):
        line = lines[j]
        if j > start and not line.strip():
            break
        collected.append(line)
    body = "\n".join([l for l in collected if l.strip()])
    return body or None

PAGE_PATTERNS = [
    re.compile(r"^\s*[PpＰｐ]\.\s*([0-9０-９]{1,4})\s*$"),
    re.compile(r"^\s*[PpＰｐ]\s*([0-9０-９]{1,4})\s*$"),
    re.compile(r"^\s*page\s*:?\s*([0-9０-９]{1,4})\s*$", re.IGNORECASE),
    re.compile(r"^\s*([0-9０-９]{1,4})\s*(?:頁|ページ|쪽)\s*$"),
]

def _detect_page(line: str) -> Optional[int]:
    for pat in PAGE_PATTERNS:
        m = pat.match(line)
        if m:
            try:
                return int(_normalize_digits(m.group(1)))
            except Exception:
                return None
    return None

def load_docx(docx_path: str) -> List[Dict]:
    out: List[Dict] = []
    if Document is None or not os.path.isfile(docx_path):
        return out
    try:
        doc = Document(docx_path)
        paras: List[str] = []
        for p in doc.paragraphs:
            t = p.text.strip()
            if t:
                paras.append(t)
        # 表は後回し（必要なら拡張）
        segments: List[Tuple[int, List[str]]] = []
        current_page = 1
        current_lines: List[str] = []
        for line in paras:
            pnum = _detect_page(line)
            if pnum is not None:
                if current_lines:
                    segments.append((current_page, current_lines))
                    current_lines = []
                current_page = pnum
            else:
                current_lines.append(line)
        if current_lines:
            segments.append((current_page, current_lines))
        if not segments:
            text = "\n".join(paras)
            aud, topics = _detect_audience_and_topics(text, os.path.basename(docx_path))
            out.append({
                "source": os.path.basename(docx_path),
                "page": 1,
                "kind": "DOCX",
                "text": text,
                "grammar_key": extract_grammar_key(text),
                "audience": aud,
                "topics": topics,
                "plus_alpha": _detect_plus_alpha(text),
                "plus_alpha_block": _extract_plus_alpha_block(text),
            })
        else:
            for pg, lines in segments:
                body = "\n".join(lines).strip()
                if len(body) < 10:
                    continue
                aud, topics = _detect_audience_and_topics(body, os.path.basename(docx_path))
                out.append({
                    "source": os.path.basename(docx_path),
                    "page": int(pg),
                    "kind": "DOCX",
                    "text": body,
                    "grammar_key": extract_grammar_key(body),
                    "audience": aud,
                    "topics": topics,
                    "plus_alpha": _detect_plus_alpha(body),
                    "plus_alpha_block": _extract_plus_alpha_block(body),
                })
    except Exception:
        pass
    return out

def load_docx_dir(dir_path: str) -> List[Dict]:
    out: List[Dict] = []
    if not os.path.isdir(dir_path):
        return out
    for fname in sorted(os.listdir(dir_path)):
        if fname.lower().endswith('.docx'):
            out.extend(load_docx(str(Path(dir_path)/fname)))
    return out

# ===== コーパス構築 =====
DOCS: List[Dict] = []
DOC_KEY_TO_GRAMMAR: Dict[Tuple[str, int], Optional[str]] = {}

def build_corpus_and_index(data_dir: Path, single_docx_fallback: Optional[Path] = None) -> Tuple[List[Dict], Optional[SentenceTransformer], Optional[object], Optional[np.ndarray]]:
    global DOCS, DOC_KEY_TO_GRAMMAR
    docs: List[Dict] = []
    docx_docs = load_docx_dir(str(data_dir))
    if docx_docs:
        docs.extend(docx_docs)
    elif single_docx_fallback and single_docx_fallback.is_file():
        docs.extend(load_docx(str(single_docx_fallback)))
    manual = _load_manual_grammar_map(data_dir)
    if manual:
        _apply_manual_grammar_map(docs, manual)
    _propagate_grammar_keys_by_filename(docs)
    DOCS = docs
    DOC_KEY_TO_GRAMMAR = { (d.get('source'), int(d.get('page') or 0)): d.get('grammar_key') for d in docs }
    if not docs:
        return [], None, None, None
    model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
    texts = [d['text'] for d in docs]
    vecs = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
    if faiss is not None:
        index = faiss.IndexFlatIP(vecs.shape[1])
        index.add(vecs.astype('float32'))
    else:
        index = None
    return docs, model, index, vecs

def get_visible_docs(docs: List[Dict], exclude_elementary: bool = True) -> List[Dict]:
    if not exclude_elementary:
        return docs
    return [d for d in docs if d.get('audience') != 'elementary']

def list_available_grammar_keys(docs: List[Dict]) -> List[str]:
    keys = sorted({d.get('grammar_key') for d in docs if d.get('grammar_key')}, key=lambda k: int(re.findall(r"\d+", k)[0]))
    return keys

def list_available_topics(docs: List[Dict]) -> List[str]:
    topics = set()
    for d in docs:
        for t in d.get('topics') or []:
            topics.add(t)
    return sorted(topics)

def search_semantic(query: str, allowed_docs: List[Dict], model, index, vecs, k: int = 8,
                    grammar_filter: Optional[List[str]] = None,
                    audience_filter: Optional[str] = None,
                    topic_filter: Optional[List[str]] = None) -> List[Tuple[Dict, float]]:
    global DOCS
    if model is None or vecs is None:
        return []
    if allowed_docs is not None and len(allowed_docs) == 0:
        return []
    allowed_key_set = None
    if allowed_docs is not None:
        allowed_key_set = set((d.get('source'), d.get('page'), d.get('kind')) for d in allowed_docs)
    qv = model.encode([query], convert_to_numpy=True, normalize_embeddings=True)
    results: List[Tuple[int, float]] = []
    total = len(DOCS)
    topn = min(k, total)
    if index is not None:
        D, I = index.search(qv.astype('float32'), topn)
        for j, i in enumerate(I[0]):
            if i < 0:
                continue
            results.append((int(i), float(D[0][j])))
    else:
        sims = vecs @ qv[0]
        top_idx = list(np.argsort(-sims)[:topn])
        results = [(int(i), float(sims[int(i)])) for i in top_idx]
    ranked: List[Tuple[Dict, float]] = []
    for i, score in results:
        d = DOCS[i]
        if allowed_key_set is not None:
            key = (d.get('source'), d.get('page'), d.get('kind'))
            if key not in allowed_key_set:
                continue
        if grammar_filter:
            gk = d.get('grammar_key')
            if not gk or gk not in grammar_filter:
                continue
        if audience_filter in ("elementary", "general"):
            if d.get('audience') and d.get('audience') != audience_filter:
                continue
        if topic_filter:
            dt = set(d.get('topics') or [])
            if not dt.intersection(set(topic_filter)):
                continue
        ranked.append((d, score))
    return ranked
