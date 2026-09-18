"""Lightweight TF-IDF helpers for tenant memory search (Phase 20)."""

from __future__ import annotations

import math
import re
from typing import Any


def tokenize(text: str) -> list[str]:
    text = (text or "").lower()
    tokens: list[str] = []
    for t in re.split(r"[^\w\u4e00-\u9fff]+", text):
        if len(t) > 1:
            tokens.append(t)
        elif len(t) == 1 and "\u4e00" <= t <= "\u9fff":
            tokens.append(t)
    for m in re.finditer(r"[\u4e00-\u9fff]{2,}", text):
        s = m.group()
        for i in range(len(s) - 1):
            tokens.append(s[i : i + 2])
    return tokens


def _tf(tokens: list[str]) -> dict[str, float]:
    counts: dict[str, float] = {}
    for t in tokens:
        counts[t] = counts.get(t, 0.0) + 1.0
    n = float(len(tokens) or 1)
    return {k: v / n for k, v in counts.items()}


def _dot(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(k, 0.0) for k, v in a.items())


def _norm(v: dict[str, float]) -> float:
    return math.sqrt(sum(x * x for x in v.values())) or 1e-12


def rank_documents(
    query: str,
    docs: list[dict[str, Any]],
    *,
    text_key: str = "content",
    title_key: str = "title",
    top_k: int = 5,
    hybrid_alpha: float = 0.65,
) -> list[tuple[float, dict[str, Any]]]:
    """Return (score, doc) pairs ranked by hybrid TF-IDF cosine + keyword."""
    if not docs or not (query or "").strip():
        return []

    tokenized = []
    for d in docs:
        blob = f"{d.get(title_key) or ''} {d.get(text_key) or ''}"
        tokenized.append(tokenize(blob))

    df: dict[str, int] = {}
    for toks in tokenized:
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    n = max(len(docs), 1)
    idf = {t: math.log((1.0 + n) / (1.0 + c)) + 1.0 for t, c in df.items()}

    doc_vectors: list[dict[str, float]] = []
    for toks in tokenized:
        tf = _tf(toks)
        doc_vectors.append({t: tf[t] * idf.get(t, 0.0) for t in tf})

    q_tf = _tf(tokenize(query))
    qv = {t: q_tf[t] * idf.get(t, 0.0) for t in q_tf}
    qn = _norm(qv)
    q_set = set(tokenize(query))

    scored: list[tuple[float, float, dict[str, Any]]] = []
    kw_raw: list[float] = []
    for i, d in enumerate(docs):
        hay = f"{d.get(title_key) or ''} {d.get(text_key) or ''}".lower()
        title = (d.get(title_key) or "").lower()
        kw = 0.0
        for tok in q_set:
            if tok in hay:
                kw += 1.0
            if tok in title:
                kw += 0.5
        kw_raw.append(kw)
        cos = _dot(qv, doc_vectors[i]) / (qn * _norm(doc_vectors[i]))
        scored.append((cos, kw, d))

    kw_max = max(kw_raw) if kw_raw else 1.0
    kw_max = kw_max if kw_max > 0 else 1.0
    out: list[tuple[float, dict[str, Any]]] = []
    for cos, kw, d in scored:
        score = hybrid_alpha * cos + (1.0 - hybrid_alpha) * (kw / kw_max)
        out.append((score, d))
    out.sort(key=lambda x: x[0], reverse=True)
    positive = [x for x in out if x[0] > 0.02]
    pool = positive if positive else out
    return pool[:top_k]
