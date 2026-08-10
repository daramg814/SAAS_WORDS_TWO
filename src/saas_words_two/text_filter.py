from __future__ import annotations

import html
import re
import sqlite3
from dataclasses import dataclass

PAIN_PATTERNS = (
    "is there a tool",
    "what do you use",
    "how do you manage",
    "still use spreadsheets",
    "built this internally",
    "takes hours",
    "manual process",
    "nothing works well",
    "too expensive",
    "too complicated",
    "would pay for",
    "missing integration",
    "feature request",
    "workaround",
)

PROMO_MARKERS = (
    "check out my",
    "check out our",
    "we just launched",
    "sign up now",
    "use code",
    "% off",
    "free trial",
    "our new product",
    "buy now",
)

_TAG_RE = re.compile(r"<[^>]+>")
_CODE_BLOCK_RE = re.compile(r"<pre>.*?</pre>", re.IGNORECASE | re.DOTALL)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_URL_ONLY_RE = re.compile(r"https?://\S+$")


def strip_code_blocks(text: str) -> str:
    return _CODE_BLOCK_RE.sub(" ", text)


def strip_html(text: str) -> str:
    return _TAG_RE.sub(" ", html.unescape(text))


def split_sentences(text: str) -> list[str]:
    cleaned = strip_html(strip_code_blocks(text))
    return [part.strip() for part in _SENTENCE_SPLIT_RE.split(cleaned) if part.strip()]


def is_quote_line(sentence: str) -> bool:
    return sentence.startswith(">")


def is_promo(sentence: str) -> bool:
    lowered = sentence.lower()
    return any(marker in lowered for marker in PROMO_MARKERS)


def is_url_only(sentence: str) -> bool:
    return bool(_URL_ONLY_RE.fullmatch(sentence.strip()))


def matched_patterns(sentence: str) -> list[str]:
    lowered = sentence.lower()
    return [pattern for pattern in PAIN_PATTERNS if pattern in lowered]


@dataclass(frozen=True)
class CandidateSentence:
    item_id: int
    sentence: str
    matched_patterns: tuple[str, ...]


def extract_candidate_sentences(item_id: int, raw_text: str | None) -> list[CandidateSentence]:
    if not raw_text:
        return []
    candidates = []
    for sentence in split_sentences(raw_text):
        if is_quote_line(sentence) or is_promo(sentence) or is_url_only(sentence):
            continue
        patterns = matched_patterns(sentence)
        if patterns:
            candidates.append(
                CandidateSentence(item_id=item_id, sentence=sentence, matched_patterns=tuple(patterns))
            )
    return candidates


def dedupe_candidates(candidates: list[CandidateSentence]) -> list[CandidateSentence]:
    seen: set[str] = set()
    result = []
    for candidate in candidates:
        key = " ".join(candidate.sentence.lower().split())
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result


@dataclass
class FilterSummary:
    source_items: int
    source_text_units: int
    candidates_before_dedupe: int
    candidates_after_dedupe: int

    @property
    def reduction_from_source_units_pct(self) -> float:
        if self.source_text_units == 0:
            return 0.0
        return 100.0 * (1 - self.candidates_after_dedupe / self.source_text_units)


def run_filter_pass(conn: sqlite3.Connection, *, created_at: str) -> FilterSummary:
    rows = conn.execute(
        "SELECT id, title, text FROM hn_items WHERE deleted = 0 AND dead = 0"
    ).fetchall()

    all_candidates: list[CandidateSentence] = []
    source_text_units = 0
    for row in rows:
        for raw_text in (row["title"], row["text"]):
            if raw_text:
                source_text_units += 1
            all_candidates.extend(extract_candidate_sentences(row["id"], raw_text))

    deduped = dedupe_candidates(all_candidates)

    conn.execute("DELETE FROM candidate_sentences")
    conn.executemany(
        "INSERT INTO candidate_sentences (item_id, sentence, matched_patterns, created_at) "
        "VALUES (?, ?, ?, ?)",
        [
            (candidate.item_id, candidate.sentence, ",".join(candidate.matched_patterns), created_at)
            for candidate in deduped
        ],
    )
    conn.commit()

    return FilterSummary(
        source_items=len(rows),
        source_text_units=source_text_units,
        candidates_before_dedupe=len(all_candidates),
        candidates_after_dedupe=len(deduped),
    )
