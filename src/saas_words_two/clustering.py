from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .text_filter import PAIN_PATTERNS

STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "to", "of", "for", "and", "or",
    "in", "on", "at", "it", "its", "this", "that", "we", "i", "you", "our", "my",
    "with", "do", "does", "did", "be", "been", "has", "have", "had", "not", "no",
    "but", "so", "if", "as", "by", "from", "still", "use", "used", "using", "just",
    "hn", "ask", "show", "will", "can", "could", "would", "should", "get", "got",
}

_TOKEN_RE = re.compile(r"[a-zA-Z]+")
_TRIGGER_PHRASE_RE = re.compile(
    "|".join(re.escape(pattern) for pattern in PAIN_PATTERNS), re.IGNORECASE
)

CONFIDENT_THRESHOLD = 0.55
AMBIGUOUS_THRESHOLD = 0.40


def strip_trigger_phrases(sentence: str) -> str:
    """Remove the pain-pattern phrase(s) that made this a candidate in the first
    place. Without this, two otherwise-unrelated short sentences ("How do you
    manage your prompts?" vs "How do you manage your morning routine?") share
    enough of the trigger phrase to look deceptively similar under both
    token-overlap and sequence-ratio scoring."""
    return _TRIGGER_PHRASE_RE.sub(" ", sentence)


def tokenize(sentence: str) -> set[str]:
    return {
        token.lower()
        for token in _TOKEN_RE.findall(sentence)
        if len(token) > 2 and token.lower() not in STOPWORDS
    }


def token_overlap(a: str, b: str) -> float:
    tokens_a, tokens_b = tokenize(a), tokenize(b)
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def sequence_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


# Below this token-overlap, reaching AMBIGUOUS_THRESHOLD (0.40) would need
# sequence_similarity >= (0.40 - 0.5*overlap) / 0.5 = 0.65+ - i.e. two
# sentences that are ~65%+ character-identical while sharing under 15% of
# their content words. For real natural-language text those two signals are
# strongly correlated (near-identical characters implies near-identical
# words), so this essentially never happens - meaning it's safe to skip the
# expensive character-level SequenceMatcher call entirely below this bar.
# Profiling on real HN data showed SequenceMatcher.ratio() was ~85% of total
# clustering time; this cuts most of those calls without changing outcomes.
_MIN_OVERLAP_FOR_SEQUENCE_CHECK = 0.15


def _score_parts(residual_a: str, tokens_a: set[str], residual_b: str, tokens_b: set[str]) -> float:
    if not tokens_a or not tokens_b:
        return 0.0
    overlap = len(tokens_a & tokens_b) / len(tokens_a | tokens_b)
    if overlap < _MIN_OVERLAP_FOR_SEQUENCE_CHECK:
        return 0.5 * overlap
    return 0.5 * overlap + 0.5 * sequence_similarity(residual_a, residual_b)


def combined_similarity(a: str, b: str) -> float:
    residual_a = strip_trigger_phrases(a)
    residual_b = strip_trigger_phrases(b)
    return _score_parts(residual_a, tokenize(residual_a), residual_b, tokenize(residual_b))


@dataclass(frozen=True)
class Candidate:
    candidate_id: int
    item_id: int
    sentence: str
    author: str | None = None


@dataclass
class Cluster:
    cluster_id: str
    members: list[Candidate] = field(default_factory=list)
    min_similarity_to_seed: float = 1.0

    @property
    def confident(self) -> bool:
        return self.min_similarity_to_seed >= CONFIDENT_THRESHOLD

    @property
    def ambiguous(self) -> bool:
        return AMBIGUOUS_THRESHOLD <= self.min_similarity_to_seed < CONFIDENT_THRESHOLD

    @property
    def independent_user_count(self) -> int:
        authors = {member.author for member in self.members if member.author}
        return len(authors) if authors else len({member.candidate_id for member in self.members})


_MAX_TOKEN_BUCKET = 200
_MAX_CANDIDATE_COMPARISONS = 300


def cluster_candidates(candidates: list[Candidate]) -> list[Cluster]:
    """Greedy seed-based clustering with token-blocking: comparing every new
    candidate against every existing cluster is O(n * clusters), minutes-slow
    past a few thousand real candidates. An inverted index (content token ->
    cluster indices whose seed contains it) narrows comparison to clusters
    sharing a token - but indexing by *every* token still blows up on real
    data, because a handful of generic-but-not-quite-stopword tokens ("tool",
    "manage", "process") appear in a huge fraction of pain-point sentences and
    produce buckets nearly as large as the whole corpus.

    Fix: any single token's bucket is only used for blocking while it stays
    under _MAX_TOKEN_BUCKET - once a token has matched that many clusters it
    is too generic to be a useful blocking key (and, per combined_similarity,
    sharing only a generic word without other overlap rarely means "same
    problem" anyway), so further candidates skip it and rely on their other,
    more specific shared tokens instead. An overall cap bounds the union too,
    in case several mid-sized buckets combine into a large one.

    An earlier version tried "only the single rarest token" - much faster,
    but wrong: when two genuinely-matching sentences each have several
    equally-rare tokens (all bucket size 0 so far), Python's set iteration
    order can make them pick *different* tied-rarest tokens and never share a
    blocking key at all. Using every non-generic shared token avoids that.

    Trade-off: combined_similarity's sequence-ratio term could in principle
    push two sentences above AMBIGUOUS_THRESHOLD with zero token overlap, and
    blocking would miss that pairing. Reaching 0.40 with a 0 token-overlap
    term needs a >=0.80 raw sequence ratio - i.e. the sentences are ~80%
    character-identical while sharing no post-stopword content word, which in
    practice does not happen for real pain-point sentences.
    """
    clusters: list[Cluster] = []
    token_index: dict[str, list[int]] = {}
    # seed residual/tokens computed once per cluster instead of re-tokenizing
    # the same seed sentence on every candidate comparison against it.
    seed_parts: dict[int, tuple[str, set[str]]] = {}

    for candidate in candidates:
        candidate_residual = strip_trigger_phrases(candidate.sentence)
        candidate_tokens = tokenize(candidate_residual)
        candidate_cluster_indices: set[int] = set()
        for token in candidate_tokens:
            bucket = token_index.get(token)
            if bucket and len(bucket) <= _MAX_TOKEN_BUCKET:
                candidate_cluster_indices.update(bucket)
                if len(candidate_cluster_indices) >= _MAX_CANDIDATE_COMPARISONS:
                    break

        best_index: int | None = None
        best_score = 0.0
        for cluster_index in candidate_cluster_indices:
            seed_residual, seed_tokens = seed_parts[cluster_index]
            score = _score_parts(seed_residual, seed_tokens, candidate_residual, candidate_tokens)
            if score > best_score:
                best_score = score
                best_index = cluster_index

        if best_index is not None and best_score >= AMBIGUOUS_THRESHOLD:
            cluster = clusters[best_index]
            cluster.members.append(candidate)
            cluster.min_similarity_to_seed = min(cluster.min_similarity_to_seed, best_score)
        else:
            new_index = len(clusters)
            clusters.append(Cluster(cluster_id=f"C{new_index:04d}", members=[candidate]))
            seed_parts[new_index] = (candidate_residual, candidate_tokens)
            for token in candidate_tokens:
                token_index.setdefault(token, []).append(new_index)

    return clusters
