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

# design roadmap 3차 개선 "문제 군집 정확도 향상": a generic-courtesy filter,
# added after two rounds of clustering-algorithm changes (string-similarity,
# then TF-IDF cosine - see clustering.py's module comment) both failed to
# fix DEMAND-001's actual precision problem. Root cause found by re-testing
# against real collected data both times: sentences like "I'd love to hear
# your feedback and feature requests!" are SHORT and consist almost
# entirely of generic courtesy words with no topic-specific content at all -
# no bag-of-words similarity metric (weighted or not) can tell two such
# near-empty-of-content sentences apart, because there is genuinely almost
# nothing there to differentiate. This is not a similarity-scoring problem;
# it is a *candidate-quality* problem, so it is fixed here, at the same
# filtering stage that already excludes promotional/quoted/URL-only text,
# rather than by tuning yet another clustering metric.
GENERIC_COURTESY_TOKENS = frozenset(
    {
        "feedback", "feature", "features", "request", "requests", "welcome", "welcomed",
        "contribution", "contributions", "contribute", "contributing", "appreciate", "appreciated",
        "comment", "comments", "bug", "bugs", "report", "reports", "idea", "ideas",
        "suggestion", "suggestions", "curious", "workaround", "workarounds",
        "thought", "thoughts", "think", "hear", "love", "anyone", "anytime", "anything",
        "everyone", "open", "issue", "issues", "github", "thanks", "thank", "question", "questions",
        "creative", "cases", "case", "kinds", "kind", "honest", "amazing", "trying", "try",
        # DEMAND-001 follow-up (2026-08-11): GitHub's default issue-template
        # section headers ("## Current Workaround", "## Workaround (current)",
        # "Is your feature request related to a problem?") repeat verbatim
        # across thousands of unrelated repos/issues and were forming large
        # false-positive clusters (independent_user_count up to 17) despite
        # having zero actual descriptive content - the line IS the template
        # label, not a real answer filled into it.
        "current", "currently", "temporary", "attempted", "tried", "documented",
        "affected", "problem", "challenge", "related", "today", "downstream",
        "consumer", "operator", "place", "applied", "verified", "limitations",
        "users", "hitting", "available", "locally",
        # GitHub PR/issue template checkbox fields ("- [x] I have searched
        # for existing feature requests") and the recurring HN comment-
        # section agreement meme ("I would pay for this service!" with no
        # specifics) - both zero-content boilerplate once the trigger
        # phrase itself is stripped.
        "searched", "existing", "duplicates", "similar", "checked", "found",
        "submitting", "pay", "service", "agree", "needed", "possible", "solutions",
        "local", "evidence", "concrete", "patch", "result",
    }
)
_GENERIC_COURTESY_STOPWORDS = frozenset(
    {
        "the", "a", "an", "is", "are", "was", "were", "to", "of", "for", "and", "or", "in", "on", "at",
        "it", "its", "this", "that", "we", "i", "you", "your", "our", "my", "with", "do", "does", "did",
        "be", "been", "has", "have", "had", "not", "no", "but", "so", "if", "as", "by", "from", "just",
        "will", "can", "could", "would", "should", "get", "got", "any", "some", "all", "both", "me",
    }
)
_WORD_ONLY_RE = re.compile(r"[a-zA-Z]+")


def _content_tokens(sentence: str) -> list[str]:
    return [
        token.lower()
        for token in _WORD_ONLY_RE.findall(sentence)
        if len(token) > 2 and token.lower() not in _GENERIC_COURTESY_STOPWORDS
    ]


def is_generic_courtesy_sentence(sentence: str, *, max_content_tokens: int = 8, min_generic_ratio: float = 0.7) -> bool:
    """True if a short sentence's content is almost entirely made of generic
    courtesy vocabulary (GENERIC_COURTESY_TOKENS) - e.g. README/Show-HN
    "feedback and feature requests welcome!" boilerplate - with essentially
    no topic-specific words. Length-gated (max_content_tokens) so a longer,
    genuinely specific sentence that happens to use a couple of these words
    ("the feature request tracker we built manually tracks vendor renewal
    dates") is not caught by this."""
    tokens = _content_tokens(sentence)
    if not tokens or len(tokens) > max_content_tokens:
        return False
    generic_count = sum(1 for token in tokens if token in GENERIC_COURTESY_TOKENS)
    return generic_count / len(tokens) >= min_generic_ratio

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
        if (
            is_quote_line(sentence)
            or is_promo(sentence)
            or is_url_only(sentence)
            or is_generic_courtesy_sentence(sentence)
        ):
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
