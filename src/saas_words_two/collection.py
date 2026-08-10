from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from . import hn_client
from .contracts import atomic_write_text


@dataclass
class AccessTestReport:
    results: dict[str, dict]

    def to_markdown(self, generated_at: str) -> str:
        lines = ["# Data Source Access Test Report", "", f"Generated: {generated_at}", ""]
        for name, info in self.results.items():
            lines.append(f"## {name}")
            lines.append(f"- status: {info['status']}")
            lines.append(f"- detail: {info['detail']}")
            lines.append("")
        return "\n".join(lines) + "\n"


def run_access_test(
    project_root: Path,
    sources_config: dict,
    session,
    *,
    generated_at: str,
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

    for name in sources_config["sources"]:
        if name == "hacker_news":
            continue
        results[name] = {
            "status": "DISABLED",
            "detail": "optional source, activation_gate not exercised in this batch",
        }

    report = AccessTestReport(results=results)
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


def _insert_item(conn: sqlite3.Connection, raw: dict, fetched_at: str) -> None:
    normalized = hn_client.normalize_item(raw)
    conn.execute(
        "INSERT OR IGNORE INTO hn_items "
        "(id, type, by, time, text, title, url, parent, score, descendants, dead, deleted, fetched_at) "
        "VALUES (:id, :type, :by, :time, :text, :title, :url, :parent, :score, :descendants, "
        ":dead, :deleted, :fetched_at)",
        {**normalized, "fetched_at": fetched_at},
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
        _insert_item(conn, result.data, fetched_at)
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
            _insert_item(conn, kid_result.data, fetched_at)
            summary.fetched_comments += 1
            max_cursor = max(max_cursor, kid_id)

    conn.commit()
    summary.cursor_after = max_cursor
    if max_cursor > summary.cursor_before:
        write_cursor(project_root, sources_config, max_cursor)
    return summary
