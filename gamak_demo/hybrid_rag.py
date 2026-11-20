"""Hybrid RAG over the response manual using watsonx.ai embeddings or local TF cosine."""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import httpx2
from pydantic import BaseModel

from .watsonx_ai import WatsonxAISettings, embed_texts

MANUAL_PATH: Final = Path(__file__).resolve().parent.parent / "data" / "gamak-manual.json"
_TOKEN_RE: Final = re.compile(r"[가-힣A-Za-z0-9]+")


class ManualEntry(BaseModel):
    id: str
    level: str
    category: str
    title: str
    content: str


class ManualCatalog(BaseModel):
    entries: tuple[ManualEntry, ...]


@dataclass(frozen=True, slots=True)
class HybridHit:
    entry: ManualEntry
    score: float
    method: str


def read_manual(path: Path = MANUAL_PATH) -> tuple[ManualEntry, ...]:
    if not path.exists():
        return ()
    return ManualCatalog.model_validate_json(path.read_text(encoding="utf-8")).entries


def _ngrams(text: str) -> Counter[str]:
    tokens = _TOKEN_RE.findall(text.lower())
    grams: list[str] = []
    for token in tokens:
        grams.append(token)
        if len(token) >= 2:
            grams.extend(token[i : i + 2] for i in range(len(token) - 1))
    return Counter(grams)


def _cosine_counter(a: Counter[str], b: Counter[str]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(a[k] * b[k] for k in a.keys() & b.keys())
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


def _cosine_dense(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


def search_manual(
    query: str,
    *,
    levels: tuple[str, ...] = (),
    top_k: int = 2,
    manual_path: Path = MANUAL_PATH,
    settings: WatsonxAISettings | None = None,
) -> tuple[HybridHit, ...]:
    """Retrieve the most relevant operational manual entries with optional watsonx.ai embeddings."""
    entries = read_manual(manual_path)
    if not entries:
        return ()

    active_settings = settings if settings is not None else WatsonxAISettings.from_env()
    dense_scores: list[float] | None = None
    method = "hybrid-lexical"

    if active_settings is not None:
        try:
            docs = [f"{e.level} {e.title} {e.content}" for e in entries]
            vectors = embed_texts([query, *docs], active_settings)
            if len(vectors) == len(entries) + 1:
                q_vec, doc_vecs = vectors[0], vectors[1:]
                dense_scores = [_cosine_dense(q_vec, d_vec) for d_vec in doc_vecs]
                method = f"watsonx-embed ({active_settings.embed_model_id})"
        except (httpx2.HTTPError, KeyError, ValueError):
            dense_scores = None

    q_grams = _ngrams(f"{query} {' '.join(levels)}")
    hits: list[HybridHit] = []
    for idx, entry in enumerate(entries):
        lexical = _cosine_counter(q_grams, _ngrams(f"{entry.level} {entry.title} {entry.content}"))
        level_boost = 0.25 if entry.level in levels else 0.0
        dense = dense_scores[idx] if dense_scores is not None else 0.0
        score = round((0.6 * dense + 0.4 * lexical + level_boost) if dense_scores else (lexical + level_boost), 4)
        hits.append(HybridHit(entry=entry, score=min(score, 1.0), method=method))

    hits.sort(key=lambda item: item.score, reverse=True)
    return tuple(hits[:top_k])
