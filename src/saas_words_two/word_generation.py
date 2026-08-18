"""단어뱅크 조합 생성 (2026-08-18 두 번째 프로젝트 정의 전환).

"정확히 500개 선정" 목표와 업계 30% 분산 상한이 폐기되면서(word_pipeline.py
참고), 이 모듈이 재사용하던 `title_generation.py`(라운드 확대 전략/분산 상한
순수 함수)는 더 이상 어디서도 호출되지 않아 파일째 삭제됐다. 이 모듈은 이제
`generate_combinations`(도메인어+기능어 조합 생성, exclude 집합 기반 중복
방지) 하나만 담당한다.
"""

from __future__ import annotations

from . import word_bank
from .contracts import normalize_title, reverse_normalized_title


def _round_robin_domain_words(domain_words: dict[str, tuple[str, ...]]) -> list[tuple[str, str]]:
    """(industry, word) pairs in the same industry-interleaved order
    `generate_combinations` has always used (industry0-word0, industry1-word0,
    ..., industry0-word1, ...), but built generically (does not assume every
    industry has the same number of domain words - an industry with fewer
    words just drops out of later layers instead of wrapping/repeating)."""
    industries = list(domain_words.keys())
    max_len = max((len(domain_words[industry]) for industry in industries), default=0)
    ordered: list[tuple[str, str]] = []
    for layer in range(max_len):
        for industry in industries:
            words = domain_words[industry]
            if layer < len(words):
                ordered.append((industry, words[layer]))
    return ordered


def generate_combinations(
    count: int,
    *,
    exclude: set[str] = frozenset(),
    domain_words: dict[str, tuple[str, ...]] | None = None,
    function_words: tuple[str, ...] | None = None,
) -> list[dict]:
    """Deterministic round-robin over industries and, within each industry,
    over its domain words - paired with a function word chosen so that every
    (domain word, function word) pair is reachable, not just a subset.

    2026-08-17 bugfix (GKP-001, discovered while validating the 42-industry/
    74-function-word expansion): the original scheme picked the function word
    via a single counter that incremented once per candidate regardless of
    which domain word it landed on. Whether that counter's per-domain-word
    step size (len(dw_pairs) mod len(FUNCTION_WORDS)) is coprime with
    len(FUNCTION_WORDS) is pure modular-arithmetic luck - the pre-expansion
    27x59 word bank happened to be coprime (full coverage), but 42
    industries x 12 words = 504 against 74 function words has
    gcd(504 mod 74, 74) = 2, so each domain word could only ever reach half
    of the 74 function words, capping the reachable space at 14,903 unique
    titles no matter how many attempts were made - a silent, permanent blind
    spot the "word bank exhausted" check couldn't distinguish from real
    exhaustion. (The true ceiling isn't 504 x 74 = 37,296: many domain words
    like "Compliance"/"Maintenance"/"Permit" repeat verbatim across
    industries, so distinct (industry, word) *entries* collapse to the same
    title text once paired with the same function word. The real ceiling is
    unique-domain-word-strings x function-words, minus same-word
    self-collisions and cross-listed reverse-duplicates: 346 x 74 - 5 - 10 =
    25,589, confirmed empirically after the fix below.) Fixed by, for
    domain-word position `i`
    (0-indexed in the fixed round-robin order) and generation pass `p`
    (0-indexed, incremented once per full sweep over every domain word),
    using `FUNCTION_WORDS[(i + p) % len(FUNCTION_WORDS)]`: for a fixed `i`,
    as `p` ranges over 0..len(FUNCTION_WORDS)-1 this hits every function-word
    index exactly once (a bijection, independent of len(dw_pairs)), so every
    pair is reachable within len(dw_pairs) x len(FUNCTION_WORDS) attempts
    regardless of the word bank's size. `tests/test_word_generation.py`'s
    `test_generate_combinations_can_reach_every_pair_regardless_of_word_bank_size`
    pins this with word-bank sizes chosen to be deliberately non-coprime.

    Skips any title whose normalized OR reverse-normalized form is already in
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

    2026-08-18 (self-expanding word bank): `domain_words`/`function_words`
    let a caller pass a merged pool (static `word_bank.py` + session-curated
    `config/word_bank_expansions.csv`, see `word_pipeline._merged_word_bank`)
    instead of the hardcoded module-level bank. Left at their default
    (`None`) this resolves to `word_bank.DOMAIN_WORDS`/`word_bank.FUNCTION_WORDS`
    exactly as before - existing callers and tests (including ones that
    monkeypatch `word_bank.DOMAIN_WORDS`/`FUNCTION_WORDS` directly) are
    unaffected.
    """
    if count <= 0:
        return []

    domain_words = word_bank.DOMAIN_WORDS if domain_words is None else domain_words
    function_words = word_bank.FUNCTION_WORDS if function_words is None else function_words

    dw_pairs = _round_robin_domain_words(domain_words)
    if not dw_pairs:
        return []
    n_func = len(function_words)
    seen = set(exclude) | {reverse_normalized_title(t) for t in exclude}
    results: list[dict] = []

    total_combinations = len(dw_pairs) * n_func
    max_attempts = total_combinations + 1

    attempts = 0
    pass_no = 0
    while len(results) < count and attempts < max_attempts:
        for i, (industry, domain_word) in enumerate(dw_pairs):
            if len(results) >= count or attempts >= max_attempts:
                break
            attempts += 1
            function_word = function_words[(i + pass_no) % n_func]

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
        pass_no += 1

    return results
