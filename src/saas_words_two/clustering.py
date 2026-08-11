from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .text_filter import PAIN_PATTERNS

# DEMAND-001 follow-up (2026-08-11, "다른 알고리즘 연구" round): real cluster
# content review found this list was missing common English function words -
# "your", "way", "how", "what", "there", "know" among them - letting them
# count as shared "content" between otherwise-unrelated sentences. E.g.
# "Ask HN: How do you manage your dotfiles?" vs "...your prompts in ChatGPT?"
# scored 0.45+ similarity purely from the shared "your" token plus the
# "Ask HN:"/"?" boilerplate structure inflating the character-level
# sequence-ratio term - both topics are completely unrelated. Verified via
# small synthetic probes mirroring real false-positive cluster pairs (not a
# full re-cluster each iteration - see PROJECT_PLAYBOOK.md for the method)
# that expanding to a standard-sized English stopword list eliminates these
# specific false positives while leaving genuine near-duplicates (which share
# actual content words, not just function words) unaffected.
STOPWORDS = frozenset(
    """
    the a an is are was were to of for and or in on at it its this that these those
    we i you your yours our ours my mine his her hers their theirs
    with do does did doing be been being have has had having not no nor but so if as by from
    still use used using just hn ask show will would could should shall can cannot
    get got getting how what why where when who whom which there here way
    know knowing think thinking want wanting anyone anybody something someone
    then than also very really quite about above after again all am any
    because before being below between both down during each few further
    into more most other over own same some such too under until up
    """.split()
)

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


# ---------------------------------------------------------------------------
# TF-IDF weighted cosine similarity ("B안" - design roadmap 3차 개선's
# "문제 군집 정확도 향상"; the original design source never actually says
# "임베딩"/embedding, only "cluster accuracy" - that word was a previous
# session's own gloss in HANDOFF.md, not a requirement).
#
# Root cause this targets (DEMAND-001, confirmed by reading real cluster
# content twice - HN alone, then HN+GH Archive+Stack Exchange): the highest
# independent-user-count clusters were consistently generic boilerplate
# ("feature requests welcome!", GitHub's own default issue template text,
# "how do you manage X" with X different every time) that combined_similarity
# above scores as similar because it treats every non-stopword token equally.
# TF-IDF fixes exactly this: a term that appears in most candidate sentences
# (boilerplate) gets driven toward zero weight, while a term specific to a
# handful of sentences about the same real problem keeps a high weight - so
# two sentences sharing only generic phrasing score low, and two sentences
# sharing specific, rare vocabulary score high, regardless of exact wording.
#
# This is deliberately NOT a neural/embedding model: it cannot recognize
# synonyms ("vendor tracker" vs "supplier management tool" score low here).
# It was chosen over sentence-transformers-style embeddings because (a) the
# diagnosed failure mode is boilerplate weighting, which TF-IDF directly
# fixes, not synonym gaps, (b) it needs no new dependency (stdlib math +
# collections only, unlike a ~300-500MB torch/sentence-transformers stack),
# and (c) CLAUDE.md §8 favors a stdlib solution when one actually addresses
# the diagnosed problem. If real re-testing after this change still shows
# accuracy problems that are specifically about synonym/paraphrase gaps
# (not boilerplate), that is the justified case for revisiting a real
# embedding model - documented here rather than reached for reflexively.
# ---------------------------------------------------------------------------


def compute_idf(token_sets: list[set[str]]) -> dict[str, float]:
    """Smoothed IDF (add-1 in both numerator and denominator, plus 1) so a
    term appearing in every document gets a small positive weight rather
    than exactly zero, and an unseen term (at query time) is never divided
    by zero."""
    total_docs = len(token_sets)
    document_frequency: Counter[str] = Counter()
    for tokens in token_sets:
        document_frequency.update(tokens)
    return {
        token: math.log((total_docs + 1) / (count + 1)) + 1.0
        for token, count in document_frequency.items()
    }


def tfidf_vector(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    term_frequency = Counter(tokens)
    vector = {}
    for token, count in term_frequency.items():
        weight = idf.get(token)
        if weight:
            vector[token] = count * weight
    return vector


def cosine_similarity(vector_a: dict[str, float], vector_b: dict[str, float]) -> float:
    if not vector_a or not vector_b:
        return 0.0
    # iterate the smaller vector's keys - dot product is symmetric either way
    small, large = (vector_a, vector_b) if len(vector_a) <= len(vector_b) else (vector_b, vector_a)
    dot = sum(weight * large[token] for token, weight in small.items() if token in large)
    if dot == 0.0:
        return 0.0
    norm_a = math.sqrt(sum(weight * weight for weight in vector_a.values()))
    norm_b = math.sqrt(sum(weight * weight for weight in vector_b.values()))
    return dot / (norm_a * norm_b)


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


def cluster_candidates_tfidf(candidates: list[Candidate]) -> list[Cluster]:
    """Same greedy seed-based, token-blocked clustering shape as
    cluster_candidates() above (see its docstring for why blocking is
    needed at all), but scores candidate-to-seed similarity with TF-IDF
    cosine similarity instead of combined_similarity's token-overlap +
    sequence-ratio blend - see the module-level comment above
    combined_similarity for why. IDF is computed once over the whole input
    batch before any clustering starts, so it reflects genuine corpus-wide
    term rarity rather than being recomputed per-comparison. Reuses
    CONFIDENT_THRESHOLD/AMBIGUOUS_THRESHOLD (the same constants
    Cluster.confident/ambiguous read) rather than a separate TF-IDF-specific
    pair, so retuning stays a single source of truth - a reasonable prior
    (not derived from labeled ground truth, none exists) pending the
    empirical check recorded in PROJECT_PLAYBOOK.md.
    """
    residuals: list[str] = []
    token_lists: list[list[str]] = []
    for candidate in candidates:
        residual = strip_trigger_phrases(candidate.sentence)
        residuals.append(residual)
        token_lists.append([t for t in _TOKEN_RE.findall(residual) if len(t) > 2 and t.lower() not in STOPWORDS])

    idf = compute_idf([set(tokens) for tokens in token_lists])
    vectors = [tfidf_vector(tokens, idf) for tokens in token_lists]

    clusters: list[Cluster] = []
    token_index: dict[str, list[int]] = {}
    seed_vectors: dict[int, dict[str, float]] = {}

    for i, candidate in enumerate(candidates):
        candidate_tokens = set(token_lists[i])
        candidate_vector = vectors[i]
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
            score = cosine_similarity(seed_vectors[cluster_index], candidate_vector)
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
            seed_vectors[new_index] = candidate_vector
            for token in candidate_tokens:
                token_index.setdefault(token, []).append(new_index)

    return clusters
