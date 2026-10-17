from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Iterable


TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def tokens(text: str) -> set[str]:
    return set(TOKEN_RE.findall(normalize(text)))


def lexical_score(query: str, text: str) -> float:
    q = tokens(query)
    d = tokens(text)
    if not q:
        return 0.0
    return len(q & d) / len(q)


def char_ngrams(text: str, n: int = 3) -> Counter[str]:
    compact = " ".join(normalize(text).split())
    return Counter(compact[i : i + n] for i in range(max(0, len(compact) - n + 1)))


def cosine(a: Counter[str], b: Counter[str]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def concept_score(query: str, item: dict) -> float:
    qn = normalize(query)
    aliases = [normalize(x) for x in item.get("aliases", [])]
    hits = sum(1 for alias in aliases if alias and (alias in qn or qn in alias))
    return min(1.0, hits / max(1, len(aliases))) if hits else 0.0


def hybrid_score(query: str, item: dict) -> float:
    lexical = lexical_score(query, item["text"])
    character = cosine(char_ngrams(query), char_ngrams(item["text"]))
    semantic_fixture = concept_score(query, item)
    return 0.45 * lexical + 0.35 * character + 0.20 * semantic_fixture


def rank(query: str, corpus: Iterable[dict], mode: str = "hybrid") -> list[tuple[str, float]]:
    scored = []
    for item in corpus:
        score = lexical_score(query, item["text"]) if mode == "lexical" else hybrid_score(query, item)
        scored.append((item["id"], score))
    return sorted(scored, key=lambda x: x[1], reverse=True)


def load_fixture(path: Path | None = None) -> list[dict]:
    path = path or Path(__file__).with_name("data") / "memory_synthetic.json"
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate() -> dict[str, float]:
    corpus = load_fixture()
    cases = [
        ("thelo proini ptisi", "m1"),
        ("syntomes anafores", "m2"),
        ("skoteino thema sta tools", "m3"),
        ("milame kai greeklish", "m4"),
    ]
    result = {}
    for mode in ("lexical", "hybrid"):
        hits = 0
        for query, expected in cases:
            top = rank(query, corpus, mode=mode)[0][0]
            hits += int(top == expected)
        result[f"{mode}_recall_at_1"] = hits / len(cases)
    return result


if __name__ == "__main__":
    print(json.dumps(evaluate(), indent=2, sort_keys=True))
