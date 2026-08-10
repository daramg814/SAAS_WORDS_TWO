from __future__ import annotations

import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import py7zr
import requests

# Stack Exchange site dumps are published as static per-site .7z archives on
# archive.org (not an official API - this is the same public, no-key dump
# archive.org itself documents as the way to bulk-access Stack Exchange
# content). Python's stdlib has no 7z support (zip/tar/gzip/bz2/lzma only),
# which is why py7zr (pure Python, LGPL-2.1+, actively maintained, ~1-2M
# PyPI downloads/month) was added as a dependency for this source - see
# docs/policies/04-data-source-policy.md for the license/maintenance note.
BASE_URL = "https://archive.org/download/stackexchange"

# design 3.2 calls for a single "선택 사이트" (selected site), not the full SE
# network. softwarerecs.stackexchange.com ("Software Recommendations") is
# chosen deliberately: its entire premise is "what tool/software should I use
# for X", which is exactly the demand-signal pattern text_filter.PAIN_PATTERNS
# looks for - a much better match than a large general-purpose SE site would
# be for this project's purpose.
DEFAULT_SITE = "softwarerecs.stackexchange.com"

# Item-id namespace: HN ids are ~8 digits, GH Archive entity ids are ~10-11
# digits (see db.py's COLUMN_MIGRATIONS comment) - Stack Exchange's own Post
# Id is small and per-site, so reusing it directly into hn_items.id would
# collide. Prefixing with "9" + a 3-digit site code + the zero-padded post id
# produces a 12-digit id starting with 9, safely outside both existing
# ranges for the foreseeable future (documented assumption, same pattern as
# gh_archive_client's id-range reasoning).
SITE_CODES = {
    "softwarerecs.stackexchange.com": 1,
}

QUESTION_POST_TYPE = "1"
ANSWER_POST_TYPE = "2"


class SupportsGet(Protocol):
    def get(self, url: str, timeout: float, stream: bool) -> Any: ...


@dataclass(frozen=True)
class FetchResult:
    ok: bool
    data: Any
    attempts: int
    error: str | None = None


def make_item_id(site: str, se_post_id: int) -> int:
    site_code = SITE_CODES[site]
    return int(f"9{site_code:03d}{se_post_id:08d}")


def dump_url(site: str) -> str:
    return f"{BASE_URL}/{site}.7z"


def download_dump(
    session: SupportsGet, site: str, dest_path: Path, *, retry_attempts: int = 3, timeout: float = 120.0, sleep_fn=time.sleep
) -> FetchResult:
    """Downloads the site's .7z to dest_path, skipping the download if a
    file already exists there (dumps are static, infrequent full-site
    snapshots - not worth re-fetching tens of MB on every run)."""
    if dest_path.exists() and dest_path.stat().st_size > 0:
        return FetchResult(ok=True, data={"path": dest_path, "cached": True}, attempts=0)

    url = dump_url(site)
    last_error = None
    for attempt in range(1, retry_attempts + 1):
        try:
            response = session.get(url, timeout=timeout, stream=True)
            response.raise_for_status()
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = dest_path.with_suffix(dest_path.suffix + ".part")
            with open(tmp_path, "wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
            tmp_path.replace(dest_path)
            return FetchResult(ok=True, data={"path": dest_path, "cached": False}, attempts=attempt)
        except requests.RequestException as exc:
            last_error = str(exc)
            if attempt < retry_attempts:
                sleep_fn(2 ** (attempt - 1))
    return FetchResult(ok=False, data=None, attempts=retry_attempts, error=last_error)


def extract_posts_xml(archive_path: Path, dest_dir: Path) -> Path:
    with py7zr.SevenZipFile(archive_path, mode="r") as archive:
        archive.extract(path=dest_dir, targets=["Posts.xml"])
    return dest_dir / "Posts.xml"


def _parse_creation_date(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        return None


def normalize_row(site: str, row: dict) -> dict | None:
    post_type = row.get("PostTypeId")
    if post_type not in (QUESTION_POST_TYPE, ANSWER_POST_TYPE):
        return None
    se_id = row.get("Id")
    if se_id is None:
        return None
    item_id = make_item_id(site, int(se_id))

    if post_type == QUESTION_POST_TYPE:
        return {
            "id": item_id,
            "type": "story",
            "by": row.get("OwnerUserId"),
            "time": _parse_creation_date(row.get("CreationDate")),
            "text": row.get("Body"),
            "title": row.get("Title"),
            "url": f"https://{site}/questions/{se_id}",
            "parent": None,
            "score": int(row["Score"]) if row.get("Score") else None,
            "descendants": int(row["AnswerCount"]) if row.get("AnswerCount") else None,
            "dead": 0,
            "deleted": 0,
        }

    parent_se_id = row.get("ParentId")
    return {
        "id": item_id,
        "type": "comment",
        "by": row.get("OwnerUserId"),
        "time": _parse_creation_date(row.get("CreationDate")),
        "text": row.get("Body"),
        "title": None,
        "url": f"https://{site}/questions/{parent_se_id}#{se_id}" if parent_se_id else None,
        "parent": make_item_id(site, int(parent_se_id)) if parent_se_id else None,
        "score": int(row["Score"]) if row.get("Score") else None,
        "descendants": None,
        "dead": 0,
        "deleted": 0,
    }


def iter_posts_with_se_id(site: str, posts_xml_path: Path):
    """Streaming XML parse (iterparse + elem.clear()) - Posts.xml for even a
    modest site is tens of MB and must not be loaded fully into memory.
    Yields (se_id, normalized-or-None) so callers that need the raw
    Stack Exchange post id for cursor tracking don't have to reverse
    make_item_id's encoding."""
    for _event, elem in ET.iterparse(posts_xml_path, events=("end",)):
        if elem.tag == "row":
            row = dict(elem.attrib)
            se_id = row.get("Id")
            yield (int(se_id) if se_id is not None else None, normalize_row(site, row))
        elem.clear()


def iter_normalized_posts(site: str, posts_xml_path: Path):
    for _se_id, normalized in iter_posts_with_se_id(site, posts_xml_path):
        if normalized is not None:
            yield normalized


def access_test(
    session: SupportsGet,
    *,
    site: str = DEFAULT_SITE,
    dest_path: Path | None = None,
    retry_attempts: int = 3,
    sleep_fn=time.sleep,
) -> FetchResult:
    """source-access skill procedure: download -> 7z extract -> XML parse.
    dest_path defaults to a throwaway temp file so the access test alone
    never leaves a cached dump behind if the real collector never runs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        archive_path = dest_path or (Path(tmpdir) / f"{site}.7z")
        fetched = download_dump(session, site, archive_path, retry_attempts=retry_attempts, sleep_fn=sleep_fn)
        if not fetched.ok:
            return fetched

        try:
            posts_xml_path = extract_posts_xml(archive_path, Path(tmpdir))
        except py7zr.exceptions.Bad7zFile as exc:
            return FetchResult(ok=False, data=None, attempts=fetched.attempts, error=f"bad 7z file: {exc}")

        questions = 0
        answers = 0
        for normalized in iter_normalized_posts(site, posts_xml_path):
            if normalized["type"] == "story":
                questions += 1
            else:
                answers += 1

        if questions == 0 and answers == 0:
            return FetchResult(
                ok=False, data=None, attempts=fetched.attempts, error="Posts.xml parsed to zero questions/answers"
            )

        return FetchResult(
            ok=True,
            data={"site": site, "questions": questions, "answers": answers, "cached_download": fetched.data["cached"]},
            attempts=fetched.attempts,
        )
