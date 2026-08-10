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


def combined_similarity(a: str, b: str) -> float:
    residual_a = strip_trigger_phrases(a)
    residual_b = strip_trigger_phrases(b)
    residual_tokens_a, residual_tokens_b = tokenize(residual_a), tokenize(residual_b)
    if not residual_tokens_a or not residual_tokens_b:
        return 0.0
    overlap = len(residual_tokens_a & residual_tokens_b) / len(residual_tokens_a | residual_tokens_b)
    return 0.5 * overlap + 0.5 * sequence_similarity(residual_a, residual_b)


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


def cluster_candidates(candidates: list[Candidate]) -> list[Cluster]:
    clusters: list[Cluster] = []
    for index, candidate in enumerate(candidates):
        best_cluster: Cluster | None = None
        best_score = 0.0
        for cluster in clusters:
            score = combined_similarity(cluster.members[0].sentence, candidate.sentence)
            if score > best_score:
                best_score = score
                best_cluster = cluster
        if best_cluster is not None and best_score >= AMBIGUOUS_THRESHOLD:
            best_cluster.members.append(candidate)
            best_cluster.min_similarity_to_seed = min(best_cluster.min_similarity_to_seed, best_score)
        else:
            clusters.append(Cluster(cluster_id=f"C{index:04d}", members=[candidate]))
    return clusters
