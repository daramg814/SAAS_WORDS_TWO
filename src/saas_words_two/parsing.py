from __future__ import annotations

import hashlib
from dataclasses import dataclass

REQUIRED_FIELDS_BY_TYPE = {
    "story": ("by", "time"),
    "comment": ("by", "time", "parent"),
    "job": ("by", "time"),
    "poll": ("by", "time"),
    "pollopt": ("by", "time", "parent"),
}


@dataclass
class ParseReport:
    total_items: int
    counts_by_type: dict[str, int]
    duplicate_ids: list[int]
    schema_violations: list[str]
    checksum: str

    @property
    def ok(self) -> bool:
        return not self.duplicate_ids and not self.schema_violations


def checksum_ids(item_ids: list[int]) -> str:
    blob = ",".join(str(item_id) for item_id in sorted(item_ids)).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def validate_rows(rows: list[dict]) -> ParseReport:
    seen: set[int] = set()
    duplicates: list[int] = []
    counts: dict[str, int] = {}
    violations: list[str] = []

    for row in rows:
        item_id = row["id"]
        if item_id in seen:
            duplicates.append(item_id)
        seen.add(item_id)

        item_type = row.get("type") or "unknown"
        counts[item_type] = counts.get(item_type, 0) + 1

        if row.get("deleted") or row.get("dead"):
            continue
        for field_name in REQUIRED_FIELDS_BY_TYPE.get(item_type, ()):
            if not row.get(field_name):
                violations.append(f"item {item_id} ({item_type}) missing required field '{field_name}'")

    return ParseReport(
        total_items=len(rows),
        counts_by_type=counts,
        duplicate_ids=duplicates,
        schema_violations=violations,
        checksum=checksum_ids(list(seen)),
    )


def report_to_markdown(report: ParseReport, generated_at: str) -> str:
    lines = [
        "# Parse / Validation Report",
        "",
        f"Generated: {generated_at}",
        "",
        f"Total items: {report.total_items}",
        f"Checksum (sha256 of sorted ids): {report.checksum}",
        "",
        "## Counts by type",
    ]
    for type_name, count in sorted(report.counts_by_type.items()):
        lines.append(f"- {type_name}: {count}")
    lines.append("")
    if report.duplicate_ids:
        lines.append(f"## Duplicate ids ({len(report.duplicate_ids)})")
        lines.extend(f"- {item_id}" for item_id in report.duplicate_ids)
        lines.append("")
    if report.schema_violations:
        lines.append(f"## Schema violations ({len(report.schema_violations)})")
        lines.extend(f"- {violation}" for violation in report.schema_violations)
        lines.append("")
    lines.append(f"## Result: {'PASS' if report.ok else 'FAIL'}")
    return "\n".join(lines) + "\n"
