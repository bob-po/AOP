"""Lightweight TF-IDF vector index for local RAG (no heavy ML deps)."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any


def tokenize(text: str) -> list[str]:
    """Tokenize Latin words + CJK unigrams/bigrams."""
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


@dataclass
class ScoredDoc:
    score: float
    vector_score: float
    keyword_score: float
    doc: dict[str, Any]


class TfidfIndex:
    """In-memory TF-IDF cosine retrieval over a document corpus."""

    def __init__(self) -> None:
        self.docs: list[dict[str, Any]] = []
        self.doc_vectors: list[dict[str, float]] = []
        self.idf: dict[str, float] = {}
        self._fitted = False

    def fit(self, documents: list[dict[str, Any]]) -> None:
        self.docs = list(documents)
        tokenized = [tokenize(self._doc_text(d)) for d in self.docs]
        df: dict[str, int] = {}
        for toks in tokenized:
            for t in set(toks):
                df[t] = df.get(t, 0) + 1
        n = max(len(self.docs), 1)
        self.idf = {t: math.log((1.0 + n) / (1.0 + c)) + 1.0 for t, c in df.items()}
        self.doc_vectors = []
        for toks in tokenized:
            tf = _tf(toks)
            self.doc_vectors.append({t: tf[t] * self.idf.get(t, 0.0) for t in tf})
        self._fitted = True

    @staticmethod
    def _doc_text(doc: dict[str, Any]) -> str:
        tags = " ".join(doc.get("tags") or [])
        return f"{doc.get('title') or ''} {doc.get('content') or ''} {tags}"

    def _query_vector(self, query: str) -> dict[str, float]:
        tf = _tf(tokenize(query))
        return {t: tf[t] * self.idf.get(t, 0.0) for t in tf}

    def _keyword_score(self, query: str, doc: dict[str, Any]) -> float:
        q_tokens = set(tokenize(query))
        if not q_tokens:
            return 0.0
        hay = self._doc_text(doc).lower()
        title = (doc.get("title") or "").lower()
        score = 0.0
        for tok in q_tokens:
            if tok in hay:
                score += 1.0
            if tok in title:
                score += 0.5
        return score

    def search(self, query: str, *, top_k: int = 3, hybrid_alpha: float = 0.65) -> list[ScoredDoc]:
        """Hybrid rank: alpha * cosine + (1-alpha) * normalized keyword score."""
        if not self._fitted or not self.docs:
            return []
        qv = self._query_vector(query)
        qn = _norm(qv)
        raw: list[ScoredDoc] = []
        kw_scores = [self._keyword_score(query, d) for d in self.docs]
        kw_max = max(kw_scores) if kw_scores else 1.0
        kw_max = kw_max if kw_max > 0 else 1.0

        for i, dv in enumerate(self.doc_vectors):
            cos = _dot(qv, dv) / (qn * _norm(dv))
            kw = kw_scores[i] / kw_max
            score = hybrid_alpha * cos + (1.0 - hybrid_alpha) * kw
            raw.append(
                ScoredDoc(
                    score=score,
                    vector_score=cos,
                    keyword_score=kw_scores[i],
                    doc=self.docs[i],
                )
            )
        raw.sort(key=lambda x: x.score, reverse=True)
        # Prefer positive signal; otherwise return top_k anyway for soft fallback
        positive = [x for x in raw if x.score > 0.02 or x.keyword_score > 0]
        pool = positive if positive else raw
        return pool[:top_k]
