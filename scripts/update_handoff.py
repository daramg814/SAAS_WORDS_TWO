"""현재 상태와 다음 원자 작업을 HANDOFF.md에 갱신한다."""

from __future__ import annotations

import argparse
from pathlib import Path

from saas_words_two.contracts import atomic_write_text


def render_handoff(
    *,
    status: str,
    current_stage: str,
    last_verified: str,
    next_action: str,
    caution: str = "",
    prohibited: str = "",
) -> str:
    lines = [
        "# HANDOFF",
        "",
        f"- 상태: `{status}`",
        f"- 현재 단계: {current_stage}",
        f"- 마지막 검증: {last_verified}",
        f"- 다음 원자 작업: {next_action}",
    ]
    if caution:
        lines.append(f"- 주의: {caution}")
    if prohibited:
        lines.append(f"- 금지: {prohibited}")
    return "\n".join(lines) + "\n"


def update_handoff(
    project_root: Path,
    *,
    status: str,
    current_stage: str,
    last_verified: str,
    next_action: str,
    caution: str = "",
    prohibited: str = "",
) -> Path:
    content = render_handoff(
        status=status,
        current_stage=current_stage,
        last_verified=last_verified,
        next_action=next_action,
        caution=caution,
        prohibited=prohibited,
    )
    path = project_root / "memory" / "HANDOFF.md"
    atomic_write_text(path, content)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--status", required=True)
    parser.add_argument("--current-stage", required=True)
    parser.add_argument("--last-verified", required=True)
    parser.add_argument("--next-action", required=True)
    parser.add_argument("--caution", default="")
    parser.add_argument("--prohibited", default="")
    args = parser.parse_args(argv)

    path = update_handoff(
        args.project_root,
        status=args.status,
        current_stage=args.current_stage,
        last_verified=args.last_verified,
        next_action=args.next_action,
        caution=args.caution,
        prohibited=args.prohibited,
    )
    print(f"HANDOFF UPDATED: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
