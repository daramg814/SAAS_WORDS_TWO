from __future__ import annotations

import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def now_kst() -> datetime:
    return datetime.now(KST)


def format_run_id(mode: str, when: datetime) -> str:
    prefix = "QA" if mode == "qa" else "RUN"
    return f"{prefix}-{when.strftime('%Y%m%d-%H%M%S')}-KST"


def format_generated_filename(when: datetime) -> str:
    return f"saas_words_{when.strftime('%Y%m%d_%H%M%S')}_KST.txt"


def _next_sequence(conn: sqlite3.Connection, name: str) -> int:
    row = conn.execute(
        "INSERT INTO id_counters(sequence_name, next_value) VALUES (?, 1) "
        "ON CONFLICT(sequence_name) DO UPDATE SET next_value = next_value + 1 "
        "RETURNING next_value",
        (name,),
    ).fetchone()
    conn.commit()
    return row[0]


def next_problem_id(conn: sqlite3.Connection) -> str:
    return f"P-{_next_sequence(conn, 'problem_id'):04d}"


def next_evidence_id(conn: sqlite3.Connection) -> str:
    return f"E-{_next_sequence(conn, 'evidence_id'):04d}"


def next_product_id(conn: sqlite3.Connection) -> str:
    return f"S-{_next_sequence(conn, 'product_id'):04d}"


def next_validation_id(conn: sqlite3.Connection, when: datetime) -> str:
    day = when.strftime("%Y%m%d")
    seq = _next_sequence(conn, f"validation_id:{day}")
    return f"GVQ-{day}-{seq:04d}"


def next_observation_id(conn: sqlite3.Connection, when: datetime) -> str:
    day = when.strftime("%Y%m%d")
    seq = _next_sequence(conn, f"observation_id:{day}")
    return f"HGO-{day}-{seq:04d}"
