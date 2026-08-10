from __future__ import annotations

import re
from dataclasses import dataclass, field

SUPPLY_SCARCITY_SCORE_MIN = 65
SUPPLY_TYPE_WEIGHTS = {"direct": 1.0, "partial": 0.4, "generic": 0.1, "noncompeting": 0.0}
ACTIVE_SIGNALS_MIN = 3

_SHOW_HN_PREFIX_RE = re.compile(r"^\s*show\s*hn\s*:\s*", re.IGNORECASE)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def normalize_product_name(raw_title: str) -> str:
    """Show HN titles are typically "Show HN: Name – short pitch"; keep just
    the product name segment for deduping/display."""
    without_prefix = _SHOW_HN_PREFIX_RE.sub("", raw_title).strip()
    for separator in (" – ", " — ", " - ", ": "):
        if separator in without_prefix:
            return without_prefix.split(separator, 1)[0].strip()
    return without_prefix


def dedupe_key(name: str, domain: str | None) -> str:
    if domain:
        normalized_domain = domain.lower()
        normalized_domain = normalized_domain.removeprefix("www.")
        return _NON_ALNUM_RE.sub("", normalized_domain)
    return _NON_ALNUM_RE.sub("", name.lower())


@dataclass
class SupplyCandidate:
    name: str
    domain: str | None
    source: str
    item_id: int
    evidence_url: str | None = None


@dataclass
class DedupedProduct:
    dedupe_key: str
    name: str
    domain: str | None
    sources: list[SupplyCandidate] = field(default_factory=list)


def deduplicate_candidates(candidates: list[SupplyCandidate]) -> list[DedupedProduct]:
    by_key: dict[str, DedupedProduct] = {}
    for candidate in candidates:
        key = dedupe_key(candidate.name, candidate.domain)
        if key not in by_key:
            by_key[key] = DedupedProduct(dedupe_key=key, name=candidate.name, domain=candidate.domain)
        by_key[key].sources.append(candidate)
    return list(by_key.values())


def active_signal_count(signals: dict[str, bool]) -> int:
    return sum(1 for satisfied in signals.values() if satisfied)


def is_active_supply(signals: dict[str, bool]) -> bool:
    return active_signal_count(signals) >= ACTIVE_SIGNALS_MIN


def effective_supply(verified_products: list[dict]) -> float:
    """verified_products: [{"active": bool, "supply_type": "direct"|"partial"|"generic"|"noncompeting"}]"""
    return sum(
        SUPPLY_TYPE_WEIGHTS.get(product["supply_type"], 0.0)
        for product in verified_products
        if product.get("active")
    )


def effective_supply_score(effective_supply_value: float) -> int:
    if effective_supply_value <= 2:
        return 40
    if effective_supply_value <= 5:
        return 30
    if effective_supply_value <= 10:
        return 15
    return 0


@dataclass(frozen=True)
class SupplyScarcityInput:
    effective_supply_value: float
    supply_gap_user_specific: bool
    supply_gap_no_strong_incumbent: bool
    supply_gap_no_recent_entrants: bool
    supply_gap_unresolved_complaints: bool


@dataclass(frozen=True)
class SupplyScarcityResult:
    effective_supply_score: int
    user_specific_gap_score: int
    no_strong_incumbent_score: int
    no_recent_entrants_score: int
    unresolved_complaints_score: int
    total: int
    passed: bool


def score_supply_scarcity(scarcity_input: SupplyScarcityInput) -> SupplyScarcityResult:
    scores = {
        "effective_supply_score": effective_supply_score(scarcity_input.effective_supply_value),
        "user_specific_gap_score": 20 if scarcity_input.supply_gap_user_specific else 0,
        "no_strong_incumbent_score": 15 if scarcity_input.supply_gap_no_strong_incumbent else 0,
        "no_recent_entrants_score": 10 if scarcity_input.supply_gap_no_recent_entrants else 0,
        "unresolved_complaints_score": 15 if scarcity_input.supply_gap_unresolved_complaints else 0,
    }
    total = sum(scores.values())
    passed = (
        total >= SUPPLY_SCARCITY_SCORE_MIN
        and scarcity_input.supply_gap_no_strong_incumbent
        and (scarcity_input.supply_gap_user_specific or scarcity_input.supply_gap_unresolved_complaints)
    )
    return SupplyScarcityResult(**scores, total=total, passed=passed)


def scarcity_grade(effective_supply_value: float, direct_competitor_count: int, scarcity_score: int) -> str:
    if effective_supply_value <= 2 and direct_competitor_count <= 2 and scarcity_score >= 80:
        return "S"
    if effective_supply_value <= 5 and scarcity_score >= 70:
        return "A"
    if effective_supply_value <= 10 and scarcity_score >= 65:
        return "B"
    return "C"
