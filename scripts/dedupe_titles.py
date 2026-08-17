
from __future__ import annotations

import argparse
from pathlib import Path

from saas_words_two.contracts import normalize_title, reverse_normalized_title, validate_title


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("input_file", type=Path)
    p.add_argument("output_file", type=Path)
    p.add_argument("--history", type=Path, default=Path("output/deliverables/history/words.txt"))
    args = p.parse_args(argv)

    history = set()
    if args.history.exists():
        history = {normalize_title(x) for x in args.history.read_text(encoding="utf-8").splitlines() if x.strip()}

    accepted: list[str] = []
    seen: set[str] = set()
    for raw in args.input_file.read_text(encoding="utf-8").splitlines():
        title = raw.strip()
        if not validate_title(title).valid:
            continue
        norm = normalize_title(title)
        rev = reverse_normalized_title(title)
        if norm in history or norm in seen or rev in seen:
            continue
        accepted.append(title)
        seen.add(norm)

    args.output_file.parent.mkdir(parents=True, exist_ok=True)
    args.output_file.write_text("\n".join(accepted) + ("\n" if accepted else ""), encoding="utf-8", newline="\n")
    print(f"accepted={len(accepted)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
