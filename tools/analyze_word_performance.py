"""단어 성과 분석 CLI (2026-08-18 학습 루프).

누적 Keyword Planner 캐시(문서②)를 분석해 성과 리포트를 갱신하고,
`--apply-retirement`를 주면 통과 0건이 확정된 기능어를
`config/retired_function_words.csv`에 병합한다(이후 라운드의 조합 생성에서
자동 제외됨 - `word_pipeline._merged_word_bank` 참고).

사용:
    python tools/analyze_word_performance.py                    # 리포트만 갱신
    python tools/analyze_word_performance.py --apply-retirement # + 은퇴 목록 갱신
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from saas_words_two import ids, word_performance  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--apply-retirement", action="store_true")
    parser.add_argument(
        "--min-attempts",
        type=int,
        default=word_performance.RETIREMENT_MIN_ATTEMPTS,
        help="은퇴 판정 최소 시도 수 (기본 %(default)s)",
    )
    args = parser.parse_args()

    rows = word_performance.load_cache_rows(args.project_root)
    if not rows:
        print("keyword_metrics_cache.csv 가 비어 있거나 없음 - 분석할 데이터 없음")
        return 1

    fn_stats = word_performance.function_word_stats(rows)
    total_pass = sum(p for p, _ in fn_stats.values())
    total = sum(t for _, t in fn_stats.values())
    print(f"누적 통과율: {total_pass}/{total} = {100.0 * total_pass / total:.2f}%")

    candidates = word_performance.retirement_candidates(fn_stats, min_attempts=args.min_attempts)
    already = word_performance.load_retired_function_words(args.project_root)
    fresh = [(w, p, t) for w, p, t in candidates if w not in already]
    print(f"은퇴 대상(통과 0/시도 {args.min_attempts}+): {len(candidates)}개, 그중 신규 {len(fresh)}개")
    if fresh:
        print("  신규: " + ", ".join(w for w, _, _ in fresh))

    if args.apply_retirement and fresh:
        added = word_performance.merge_retired_function_words(
            args.project_root, fresh, ids.now_kst().isoformat()
        )
        print(f"은퇴 목록에 {added}개 추가: {word_performance.retired_function_words_path(args.project_root)}")
    elif fresh:
        print("(--apply-retirement 를 주면 은퇴 목록에 반영됩니다)")

    report = word_performance.write_report(args.project_root, ids.now_kst())
    print(f"리포트 갱신: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
