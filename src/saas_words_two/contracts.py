
from __future__ import annotations

import hashlib
import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

TITLE_PATTERN = re.compile(r"^[A-Z][a-z]* [A-Z][a-z]*$")


@dataclass(frozen=True)
class TitleValidationResult:
    valid: bool
    errors: tuple[str, ...]


def normalize_title(title: str) -> str:
    return " ".join(title.strip().split()).casefold()


def reverse_normalized_title(title: str) -> str:
    words = normalize_title(title).split(" ")
    return " ".join(reversed(words)) if len(words) == 2 else normalize_title(title)


def validate_title(title: str) -> TitleValidationResult:
    errors: list[str] = []
    if title != title.strip():
        errors.append("leading_or_trailing_whitespace")
    if "  " in title:
        errors.append("multiple_spaces")
    if not TITLE_PATTERN.fullmatch(title):
        errors.append("not_two_title_case_alpha_words")
    return TitleValidationResult(not errors, tuple(errors))


def validate_title_set(
    titles: Iterable[str],
    *,
    target_count: int,
    history: Iterable[str] = (),
    blocklist: Iterable[str] = (),
) -> list[str]:
    title_list = list(titles)
    errors: list[str] = []
    if len(title_list) != target_count:
        errors.append(f"wrong_count:{len(title_list)}!=target:{target_count}")

    history_norm = {normalize_title(x) for x in history if x.strip()}
    block_norm = {normalize_title(x) for x in blocklist if x.strip()}
    seen: set[str] = set()
    seen_reverse: set[str] = set()

    for line_no, title in enumerate(title_list, 1):
        result = validate_title(title)
        errors.extend(f"line_{line_no}:{e}" for e in result.errors)
        norm = normalize_title(title)
        rev = reverse_normalized_title(title)
        if norm in seen:
            errors.append(f"line_{line_no}:duplicate_current_run")
        if norm in seen_reverse or rev in seen:
            errors.append(f"line_{line_no}:reverse_duplicate")
        if norm in history_norm:
            errors.append(f"line_{line_no}:duplicate_history")
        if norm in block_norm:
            errors.append(f"line_{line_no}:blocklist_violation")
        seen.add(norm)
        seen_reverse.add(rev)
    return errors


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        _replace_with_retry(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _replace_with_retry(tmp_path: Path, path: Path, attempts: int = 5, base_delay: float = 0.2) -> None:
    """os.replace on Windows can transiently fail with PermissionError (WinError 5)
    when another process (antivirus/indexer) briefly holds the destination open -
    retry with backoff instead of failing a whole pipeline stage over it."""
    for attempt in range(attempts):
        try:
            os.replace(tmp_path, path)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(base_delay * (2**attempt))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
