"""단어뱅크 조합 생성 (2026-08-11 프로젝트 정의 전환).

design 9.1/9.3의 라운드 확대 전략(부족분 x2, 최대 5라운드)과 9.1의 "최소 5개
분산, 30% 상한" 원칙은 그대로 유지하되, 그 대상을 "기회(problem_id)"에서
"업계(industry)"로 바꿨다. `title_generation.py`의 순수 수학 함수들
(first_round_size/next_round_size/max_titles_per_opportunity/
check_distribution/select_final_titles)은 애초에 opportunity-특정 로직이
아니라 dict의 "problem_id"/"priority_score" 키만 보므로 그대로 재사용한다
(industry를 problem_id 자리에 넣는다) - 중복 구현하지 않는다.
"""

from __future__ import annotations

from . import title_generation, word_bank
from .contracts import normalize_title, reverse_normalized_title

MAX_ROUNDS = title_generation.MAX_ROUNDS


def generate_combinations(count: int, *, exclude: set[str] = frozenset()) -> list[dict]:
    """Deterministic round-robin over industries and, within each industry,
    over its domain words - paired with a rotating function word so neither
    a single industry nor a single function word dominates a batch. Skips
    any title whose normalized OR reverse-normalized form is already in
    `exclude` (previously generated/approved/rejected this run, plus
    history/blocklist - callers pass the union) and any accidental
    domain==function collision.

    Reverse-duplicate checking happens here, not just at final
    `contracts.validate_title_set` time, because a handful of words (Grid,
    Meter, Ledger, Terminal, Route as of 2026-08-17) are cross-listed as both
    a domain word (in one industry) and a function word - at small batch
    sizes the odds of generating both "A B" and "B A" in the same round were
    low enough to go unnoticed, but a 10,000-candidate round (GKP-001's
    --first-round-size override) produced 6 such pairs. Skipping them here
    means the AI judgment step never sees them and `validate_title_set` can't
    fail the whole run over it later.

    Returns fewer than `count` items only if the entire word bank is
    exhausted - callers should treat that as real exhaustion, not a bug.
    (As of 2026-08-17: 504 (industry, domain word) entries across 42
    industries x 74 function words - some words like Claim/Ledger/Permit
    repeat across industries, so unique domain words are fewer than 504.)
    """
    if count <= 0:
        return []

    industries = word_bank.all_industries()
    domain_cursors = {industry: 0 for industry in industries}
    function_cursor = 0
    industry_index = 0
    seen = set(exclude) | {reverse_normalized_title(t) for t in exclude}
    results: list[dict] = []

    total_combinations = sum(len(words) for words in word_bank.DOMAIN_WORDS.values()) * len(
        word_bank.FUNCTION_WORDS
    )
    max_attempts = total_combinations + 1

    attempts = 0
    while len(results) < count and attempts < max_attempts:
        attempts += 1
        industry = industries[industry_index % len(industries)]
        industry_index += 1
        domain_words = word_bank.DOMAIN_WORDS[industry]
        domain_word = domain_words[domain_cursors[industry] % len(domain_words)]
        domain_cursors[industry] += 1
        function_word = word_bank.FUNCTION_WORDS[function_cursor % len(word_bank.FUNCTION_WORDS)]
        function_cursor += 1

        if domain_word == function_word:
            continue
        title = f"{domain_word} {function_word}"
        norm = normalize_title(title)
        rev = reverse_normalized_title(title)
        if norm in seen or rev in seen:
            continue
        seen.add(norm)
        seen.add(rev)
        results.append({"title": title, "industry": industry})

    return results
