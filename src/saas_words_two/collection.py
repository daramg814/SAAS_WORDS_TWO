from __future__ import annotations

import shutil
import sqlite3
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import gh_archive_client, hn_client, npm_client, stack_exchange_client
from .contracts import atomic_write_text

# Below this much free disk space, collection should not proceed - not a
# precise budget calculation (no such number is specified in the design),
# just a floor low enough that "the disk is actually full" is caught rather
# than silently attempted and failing mid-write.
MIN_FREE_DISK_BYTES = 200 * 1024 * 1024


def check_disk_usage(project_root: Path) -> dict:
    """Design 3.3 access-test step 5 ('디스크 사용량 확인'). Reports free space on
    the project's drive plus the size of the two things that actually grow
    with collection (data/local.db and data/cache/) so a session can see disk
    pressure before it becomes a write failure."""
    usage = shutil.disk_usage(project_root)
    db_path = project_root / "data" / "local.db"
    cache_dir = project_root / "data" / "cache"
    cache_bytes = sum(f.stat().st_size for f in cache_dir.glob("**/*") if f.is_file()) if cache_dir.exists() else 0
    return {
        "free_bytes": usage.free,
        "total_bytes": usage.total,
        "local_db_bytes": db_path.stat().st_size if db_path.exists() else 0,
        "cache_bytes": cache_bytes,
        "ok": usage.free >= MIN_FREE_DISK_BYTES,
    }


@dataclass
class AccessTestReport:
    results: dict[str, dict]
    disk_usage: dict

    def to_markdown(self, generated_at: str) -> str:
        lines = ["# Data Source Access Test Report", "", f"Generated: {generated_at}", ""]
        for name, info in self.results.items():
            lines.append(f"## {name}")
            lines.append(f"- status: {info['status']}")
            lines.append(f"- detail: {info['detail']}")
            lines.append("")
        lines.append("## disk_usage")
        lines.append(f"- free_bytes: {self.disk_usage['free_bytes']}")
        lines.append(f"- total_bytes: {self.disk_usage['total_bytes']}")
        lines.append(f"- local_db_bytes: {self.disk_usage['local_db_bytes']}")
        lines.append(f"- cache_bytes: {self.disk_usage['cache_bytes']}")
        lines.append(f"- ok: {self.disk_usage['ok']}")
        lines.append("")
        return "\n".join(lines) + "\n"


def run_access_test(
    project_root: Path,
    sources_config: dict,
    session,
    *,
    generated_at: str,
    gh_archive_hour: str | None = None,
    stack_exchange_dump_path: Path | None = None,
) -> AccessTestReport:
    results: dict[str, dict] = {}
    hn_conf = sources_config["sources"]["hacker_news"]
    if hn_conf.get("enabled") and hn_conf.get("required"):
        result = hn_client.access_test(session)
        if result.ok:
            results["hacker_news"] = {
                "status": "PASS",
                "detail": f"maxitem={result.data['max_item']} sample_id={result.data['sample_item'].get('id')}",
            }
        else:
            results["hacker_news"] = {"status": "FAIL", "detail": result.error or "unknown error"}
    else:
        results["hacker_news"] = {"status": "DISABLED", "detail": "required source disabled in config"}

    if "gh_archive" in sources_config["sources"]:
        gh_result = gh_archive_client.access_test(session, hour=gh_archive_hour)
        if gh_result.ok:
            results["gh_archive"] = {
                "status": "PASS",
                "detail": (
                    f"hour={gh_result.data['hour']} total_events={gh_result.data['total_events']} "
                    f"normalizable_events={gh_result.data['normalizable_events']} "
                    f"compressed_bytes={gh_result.data['compressed_bytes']}"
                ),
            }
        else:
            results["gh_archive"] = {"status": "FAIL", "detail": gh_result.error or "unknown error"}

    se_conf = sources_config["sources"].get("stack_exchange_dump")
    # "site" presence distinguishes a genuinely configured source from a bare
    # {"enabled": False} placeholder entry - without a site there is nothing
    # to test a connection against, so there is no real access test to run.
    if se_conf and "site" in se_conf:
        site = se_conf["site"]
        dump_path = stack_exchange_dump_path or (
            project_root / se_conf.get("dump_cache_path", f"data/raw/stack_exchange/{site}.7z")
        )
        se_result = stack_exchange_client.access_test(session, site=site, dest_path=dump_path)
        if se_result.ok:
            results["stack_exchange_dump"] = {
                "status": "PASS",
                "detail": (
                    f"site={se_result.data['site']} questions={se_result.data['questions']} "
                    f"answers={se_result.data['answers']} cached_download={se_result.data['cached_download']}"
                ),
            }
        else:
            results["stack_exchange_dump"] = {"status": "FAIL", "detail": se_result.error or "unknown error"}

    if "npm_registry" in sources_config["sources"]:
        npm_result = npm_client.access_test(session)
        if npm_result.ok:
            results["npm_registry"] = {
                "status": "PASS",
                "detail": f"total={npm_result.data['total']} sample_name={npm_result.data['sample_name']}",
            }
        else:
            results["npm_registry"] = {"status": "FAIL", "detail": npm_result.error or "unknown error"}

    for name in sources_config["sources"]:
        if name in results:
            continue
        results[name] = {
            "status": "DISABLED",
            "detail": "optional source, activation_gate not exercised in this batch",
        }

    report = AccessTestReport(results=results, disk_usage=check_disk_usage(project_root))
    report_path = project_root / "output" / "logs" / "access_test_report.md"
    atomic_write_text(report_path, report.to_markdown(generated_at))
    return report


@dataclass
class CollectionSummary:
    fetched_stories: int = 0
    fetched_comments: int = 0
    skipped_existing: int = 0
    errors: list[str] = field(default_factory=list)
    cursor_before: int = 0
    cursor_after: int = 0


def _cursor_path(project_root: Path, sources_config: dict) -> Path:
    rel = sources_config["sources"]["hacker_news"]["incremental_cursor"]
    return project_root / rel


def read_cursor(project_root: Path, sources_config: dict) -> int:
    path = _cursor_path(project_root, sources_config)
    if not path.exists():
        return 0
    text = path.read_text(encoding="utf-8").strip()
    return int(text) if text else 0


def write_cursor(project_root: Path, sources_config: dict, value: int) -> None:
    atomic_write_text(_cursor_path(project_root, sources_config), f"{value}\n")


def _existing_ids(conn: sqlite3.Connection, candidate_ids: list[int]) -> set[int]:
    if not candidate_ids:
        return set()
    placeholders = ",".join("?" for _ in candidate_ids)
    rows = conn.execute(
        f"SELECT id FROM hn_items WHERE id IN ({placeholders})", candidate_ids
    ).fetchall()
    return {row[0] for row in rows}


def _insert_normalized(
    conn: sqlite3.Connection, normalized: dict, fetched_at: str, *, source: str = "hacker_news"
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO hn_items "
        "(id, type, by, time, text, title, url, parent, score, descendants, dead, deleted, fetched_at, source) "
        "VALUES (:id, :type, :by, :time, :text, :title, :url, :parent, :score, :descendants, "
        ":dead, :deleted, :fetched_at, :source)",
        {**normalized, "fetched_at": fetched_at, "source": source},
    )


def run_incremental_collection(
    project_root: Path,
    conn: sqlite3.Connection,
    sources_config: dict,
    hn_settings: dict,
    session,
    *,
    fetched_at: str,
) -> CollectionSummary:
    summary = CollectionSummary(cursor_before=read_cursor(project_root, sources_config))
    stories_per_list = hn_settings.get("stories_per_list", 500)
    comments_per_story = hn_settings.get("comments_per_story", 20)
    budget = hn_settings.get("max_items_per_run", 800)

    candidate_story_ids: list[int] = []
    seen: set[int] = set()
    for list_name in hn_client.STORY_LISTS:
        result = hn_client.fetch_story_list(session, list_name)
        if not result.ok:
            summary.errors.append(f"{list_name}: {result.error}")
            continue
        for item_id in result.data[:stories_per_list]:
            if item_id not in seen:
                seen.add(item_id)
                candidate_story_ids.append(item_id)

    already_have = _existing_ids(conn, candidate_story_ids)
    to_fetch = [item_id for item_id in candidate_story_ids if item_id not in already_have]
    summary.skipped_existing += len(already_have)

    max_cursor = summary.cursor_before

    for story_id in to_fetch:
        if budget <= 0:
            break
        result = hn_client.fetch_item(session, story_id)
        budget -= 1
        if not result.ok or not isinstance(result.data, dict):
            summary.errors.append(f"item {story_id}: {result.error or 'null item'}")
            continue
        _insert_normalized(conn, hn_client.normalize_item(result.data), fetched_at)
        summary.fetched_stories += 1
        max_cursor = max(max_cursor, story_id)

        kid_ids = (result.data.get("kids") or [])[:comments_per_story]
        existing_kid_ids = _existing_ids(conn, kid_ids)
        for kid_id in kid_ids:
            if budget <= 0:
                break
            if kid_id in existing_kid_ids:
                summary.skipped_existing += 1
                continue
            kid_result = hn_client.fetch_item(session, kid_id)
            budget -= 1
            if not kid_result.ok or not isinstance(kid_result.data, dict):
                summary.errors.append(f"item {kid_id}: {kid_result.error or 'null item'}")
                continue
            _insert_normalized(conn, hn_client.normalize_item(kid_result.data), fetched_at)
            summary.fetched_comments += 1
            max_cursor = max(max_cursor, kid_id)

    conn.commit()
    summary.cursor_after = max_cursor
    if max_cursor > summary.cursor_before:
        write_cursor(project_root, sources_config, max_cursor)
    return summary


def run_keyword_search_collection(
    conn: sqlite3.Connection,
    patterns: list[str],
    session,
    *,
    hits_per_pattern: int,
    budget: int,
    created_after_epoch: int,
    fetched_at: str,
) -> CollectionSummary:
    """Search HN's full history (via Algolia) for each demand-pattern phrase.

    This is the primary source of dated, independent-user evidence: the
    Firebase list-based collector above only reaches recently active items
    and cannot realistically satisfy the 24-month evidence window on its own.
    """
    summary = CollectionSummary()
    remaining = budget

    for pattern in patterns:
        if remaining <= 0:
            break
        result = hn_client.search_items(
            session,
            pattern,
            hits_per_page=min(hits_per_pattern, remaining),
            created_after_epoch=created_after_epoch,
        )
        if not result.ok:
            summary.errors.append(f"search '{pattern}': {result.error}")
            continue

        hits = result.data.get("hits", []) if isinstance(result.data, dict) else []
        hit_by_id: dict[int, dict] = {}
        for hit in hits:
            try:
                hit_by_id[int(hit["objectID"])] = hit
            except (KeyError, TypeError, ValueError):
                summary.errors.append(f"search '{pattern}': hit missing valid objectID")

        existing = _existing_ids(conn, list(hit_by_id.keys()))
        for item_id, hit in hit_by_id.items():
            if remaining <= 0:
                break
            if item_id in existing:
                summary.skipped_existing += 1
                continue
            normalized = hn_client.normalize_algolia_hit(hit)
            _insert_normalized(conn, normalized, fetched_at)
            if normalized["type"] == "story":
                summary.fetched_stories += 1
            else:
                summary.fetched_comments += 1
            remaining -= 1
            summary.cursor_after = max(summary.cursor_after, item_id)

    conn.commit()
    return summary


def _gh_archive_cursor_path(project_root: Path, sources_config: dict) -> Path:
    rel = sources_config["sources"]["gh_archive"]["incremental_cursor"]
    return project_root / rel


def read_gh_archive_cursor(project_root: Path, sources_config: dict) -> str | None:
    path = _gh_archive_cursor_path(project_root, sources_config)
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None


def write_gh_archive_cursor(project_root: Path, sources_config: dict, value: str) -> None:
    atomic_write_text(_gh_archive_cursor_path(project_root, sources_config), f"{value}\n")


@dataclass
class GhArchiveCollectionSummary:
    fetched_stories: int = 0
    fetched_comments: int = 0
    skipped_existing: int = 0
    hours_processed: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    cursor_before: str | None = None
    cursor_after: str | None = None


def run_gh_archive_collection(
    project_root: Path,
    conn: sqlite3.Connection,
    sources_config: dict,
    gh_settings: dict,
    session,
    *,
    now: datetime,
    fetched_at: str,
) -> GhArchiveCollectionSummary:
    """Incrementally collect GH Archive hourly dumps into the same hn_items
    table HN collection uses (source='gh_archive'), one run at a time.

    Backfill window: sources.yaml's gh_archive.recent_days_max is the hard
    floor - this never fetches further back than that. recent_days_min
    documents the minimum useful depth but is not separately enforced: the
    incremental cursor just keeps walking forward from the floor,
    max_hours_per_run hours per invocation (mirrors hacker_news's
    incremental_cursor pattern), until it catches up to `now` minus a
    publish-delay buffer.
    """
    gh_conf = sources_config["sources"]["gh_archive"]
    summary = GhArchiveCollectionSummary(cursor_before=read_gh_archive_cursor(project_root, sources_config))

    # GH Archive hour files are named in UTC; `now` may be any tz-aware
    # datetime (the pipeline passes KST) so it must be converted before it is
    # used to build hour keys, or every fetch targets the wrong hour.
    now_utc = now.astimezone(timezone.utc)
    floor_hour = gh_archive_client.hour_key(now_utc - timedelta(days=gh_conf["recent_days_max"]))
    # GH Archive publishes each hour's file with some delay; stay a couple of
    # hours behind "now" so we don't repeatedly retry an hour not yet available.
    ceiling_hour = gh_archive_client.hour_key(now_utc - timedelta(hours=2))
    # Hour keys have no leading zero ("...-7" vs "...-12"), so they must be
    # compared as datetimes, not strings - lexicographically "...-7" sorts
    # *after* "...-12" even though 7am is earlier.
    floor_dt = gh_archive_client.hour_key_to_datetime(floor_hour)
    ceiling_dt = gh_archive_client.hour_key_to_datetime(ceiling_hour)

    current_hour = summary.cursor_before or floor_hour
    current_dt = gh_archive_client.hour_key_to_datetime(current_hour)
    if current_dt < floor_dt:
        current_hour, current_dt = floor_hour, floor_dt

    budget = gh_settings.get("max_hours_per_run", 12)
    while budget > 0 and current_dt <= ceiling_dt:
        result = gh_archive_client.fetch_hour(session, current_hour, retry_attempts=3, timeout=30.0, sleep_fn=time.sleep)
        budget -= 1
        if not result.ok:
            summary.errors.append(f"hour {current_hour}: {result.error}")
            current_hour = gh_archive_client.next_hour_key(current_hour)
            current_dt = gh_archive_client.hour_key_to_datetime(current_hour)
            continue

        try:
            events = list(gh_archive_client.iter_hour_events(result.data))
        except OSError as exc:
            summary.errors.append(f"hour {current_hour}: gunzip failed: {exc}")
            current_hour = gh_archive_client.next_hour_key(current_hour)
            current_dt = gh_archive_client.hour_key_to_datetime(current_hour)
            continue

        normalized_by_id: dict[int, dict] = {}
        for event in events:
            normalized = gh_archive_client.normalize_event(event)
            if normalized is not None and normalized.get("id") is not None:
                normalized_by_id[normalized["id"]] = normalized

        existing = _existing_ids(conn, list(normalized_by_id.keys()))
        for item_id, normalized in normalized_by_id.items():
            if item_id in existing:
                summary.skipped_existing += 1
                continue
            _insert_normalized(conn, normalized, fetched_at, source="gh_archive")
            if normalized["type"] == "story":
                summary.fetched_stories += 1
            else:
                summary.fetched_comments += 1

        summary.hours_processed.append(current_hour)
        current_hour = gh_archive_client.next_hour_key(current_hour)
        current_dt = gh_archive_client.hour_key_to_datetime(current_hour)

    conn.commit()
    summary.cursor_after = current_hour
    if summary.cursor_after != summary.cursor_before:
        write_gh_archive_cursor(project_root, sources_config, summary.cursor_after)
    return summary


def _stack_exchange_cursor_path(project_root: Path, site: str) -> Path:
    safe_site = site.replace(".", "_")
    return project_root / "data" / "cache" / f"stack_exchange_{safe_site}_last_id.txt"


def read_stack_exchange_cursor(project_root: Path, site: str) -> int:
    path = _stack_exchange_cursor_path(project_root, site)
    if not path.exists():
        return 0
    text = path.read_text(encoding="utf-8").strip()
    return int(text) if text else 0


def write_stack_exchange_cursor(project_root: Path, site: str, value: int) -> None:
    atomic_write_text(_stack_exchange_cursor_path(project_root, site), f"{value}\n")


@dataclass
class StackExchangeCollectionSummary:
    fetched_stories: int = 0
    fetched_comments: int = 0
    skipped_existing: int = 0
    errors: list[str] = field(default_factory=list)
    cursor_before: int = 0
    cursor_after: int = 0


def run_stack_exchange_collection(
    project_root: Path,
    conn: sqlite3.Connection,
    sources_config: dict,
    se_settings: dict,
    session,
    *,
    fetched_at: str,
) -> StackExchangeCollectionSummary:
    """Stack Exchange dumps are static, infrequent full-site snapshots, not
    an hourly/incremental feed like GH Archive - "incremental" here means
    walking Posts.xml once (in ascending Id order, as the dump format
    guarantees) and resuming from the last Stack Exchange post Id processed,
    same spirit as hacker_news's incremental_cursor but keyed on the dump's
    own row order rather than a fetch cursor."""
    se_conf = sources_config["sources"]["stack_exchange_dump"]
    site = se_conf.get("site", stack_exchange_client.DEFAULT_SITE)
    dump_path = project_root / se_conf.get("dump_cache_path", f"data/raw/stack_exchange/{site}.7z")

    summary = StackExchangeCollectionSummary(cursor_before=read_stack_exchange_cursor(project_root, site))

    fetched = stack_exchange_client.download_dump(session, site, dump_path)
    if not fetched.ok:
        summary.errors.append(f"download: {fetched.error}")
        return summary

    budget = se_settings.get("max_items_per_run", 5000)
    max_se_id_seen = summary.cursor_before

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            posts_xml_path = stack_exchange_client.extract_posts_xml(dump_path, Path(tmpdir))
        except Exception as exc:  # py7zr raises its own exception hierarchy
            summary.errors.append(f"extract: {exc}")
            return summary

        batch: list[dict] = []
        for se_id, normalized in stack_exchange_client.iter_posts_with_se_id(site, posts_xml_path):
            if se_id is None or se_id <= summary.cursor_before:
                continue
            max_se_id_seen = max(max_se_id_seen, se_id)
            if normalized is None:
                continue
            batch.append(normalized)
            if len(batch) >= budget:
                break

        existing = _existing_ids(conn, [item["id"] for item in batch])
        for normalized in batch:
            if normalized["id"] in existing:
                summary.skipped_existing += 1
                continue
            _insert_normalized(conn, normalized, fetched_at, source="stack_exchange")
            if normalized["type"] == "story":
                summary.fetched_stories += 1
            else:
                summary.fetched_comments += 1

    conn.commit()
    summary.cursor_after = max_se_id_seen
    if summary.cursor_after != summary.cursor_before:
        write_stack_exchange_cursor(project_root, site, summary.cursor_after)
    return summary
