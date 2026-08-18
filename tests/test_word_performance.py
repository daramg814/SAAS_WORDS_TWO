"""word_performance(학습 루프) 테스트 - 운영 함수를 직접 호출한다."""

from __future__ import annotations

import csv

from saas_words_two import word_performance


def cache_row(title, gate_passed):
    return {
        "title": title,
        "avg_monthly_searches": "1000",
        "competition_index": "0",
        "api_status": "success",
        "gate_passed": "True" if gate_passed else "False",
        "checked_at": "t0",
    }


def write_cache(project_root, rows):
    path = word_performance.metrics_cache_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def test_function_word_stats_counts_pass_and_total_by_second_word():
    rows = [
        cache_row("Claim Portal", True),
        cache_row("Fuel Portal", False),
        cache_row("Fuel Sync", False),
        cache_row("malformed-single-token", True),  # 2단어가 아니면 무시
    ]
    stats = word_performance.function_word_stats(rows)
    assert stats == {"Portal": (1, 2), "Sync": (0, 1)}


def test_domain_word_stats_counts_by_first_word():
    rows = [cache_row("Fuel Portal", True), cache_row("Fuel Sync", False)]
    assert word_performance.domain_word_stats(rows) == {"Fuel": (1, 2)}


def test_retirement_candidates_requires_zero_pass_and_min_attempts():
    stats = {
        "Sync": (0, 300),      # 은퇴 대상
        "Toolkit": (0, 299),   # 시도 부족 -> 제외
        "Portal": (1, 300),    # 통과 있음 -> 제외
    }
    assert word_performance.retirement_candidates(stats) == [("Sync", 0, 300)]


def test_merge_retired_function_words_appends_and_dedupes(tmp_path):
    added = word_performance.merge_retired_function_words(tmp_path, [("Sync", 0, 300)], "t0")
    assert added == 1
    # 같은 단어 재병합은 no-op, 새 단어만 추가
    added = word_performance.merge_retired_function_words(
        tmp_path, [("Sync", 0, 310), ("Toolkit", 0, 305)], "t1"
    )
    assert added == 1
    retired = word_performance.load_retired_function_words(tmp_path)
    assert retired == {"Sync", "Toolkit"}
    with word_performance.retired_function_words_path(tmp_path).open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0] == {"word": "Sync", "passed": "0", "attempts": "300", "retired_at": "t0"}


def test_load_retired_function_words_missing_file_is_empty(tmp_path):
    assert word_performance.load_retired_function_words(tmp_path) == set()


def test_write_report_renders_stats_and_retired(tmp_path):
    write_cache(tmp_path, [cache_row("Claim Portal", True)] * 100 + [cache_row("Fuel Sync", False)] * 300)
    word_performance.merge_retired_function_words(tmp_path, [("Sync", 0, 300)], "t0")

    path = word_performance.write_report(tmp_path, __import__("saas_words_two.ids", fromlist=["ids"]).now_kst())
    assert path == word_performance.report_path(tmp_path)
    content = path.read_text(encoding="utf-8")
    assert "| Portal | 100 | 100 | 100.00% |" in content
    assert "Sync" in content  # 은퇴 대상 목록


def test_write_report_noop_when_cache_missing(tmp_path):
    from saas_words_two import ids

    assert word_performance.write_report(tmp_path, ids.now_kst()) is None


def test_performance_summary_for_expansion_includes_top_and_retired(tmp_path):
    write_cache(
        tmp_path,
        [cache_row("Claim Portal", True)] * 10 + [cache_row("Fuel Portal", False)] * 90
        + [cache_row("Fuel Sync", False)] * 300,
    )
    word_performance.merge_retired_function_words(tmp_path, [("Sync", 0, 300)], "t0")

    summary = word_performance.performance_summary_for_expansion(tmp_path)
    assert summary["retired_function_words"] == ["Sync"]
    top_words = [entry["word"] for entry in summary["top_function_words"]]
    assert "Portal" in top_words
    portal = next(e for e in summary["top_function_words"] if e["word"] == "Portal")
    assert portal == {"word": "Portal", "passed": 10, "attempts": 100, "pass_rate_pct": 10.0}
