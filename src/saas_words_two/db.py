from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS id_counters (
    sequence_name TEXT PRIMARY KEY,
    next_value INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS hn_items (
    id INTEGER PRIMARY KEY,
    type TEXT,
    by TEXT,
    time INTEGER,
    text TEXT,
    title TEXT,
    url TEXT,
    parent INTEGER,
    score INTEGER,
    descendants INTEGER,
    dead INTEGER NOT NULL DEFAULT 0,
    deleted INTEGER NOT NULL DEFAULT 0,
    fetched_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'hacker_news'
);

CREATE TABLE IF NOT EXISTS candidate_sentences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES hn_items(id),
    sentence TEXT NOT NULL,
    matched_patterns TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS problems (
    problem_id TEXT PRIMARY KEY,
    target_user TEXT,
    task TEXT,
    workaround TEXT,
    pain TEXT,
    impact TEXT,
    desired_outcome TEXT,
    frequency TEXT NOT NULL DEFAULT 'unknown',
    risk_severity TEXT NOT NULL DEFAULT 'none',
    purchase_intent TEXT NOT NULL DEFAULT 'none',
    has_manual_or_complaint_evidence INTEGER NOT NULL DEFAULT 0,
    supply_gap_user_specific INTEGER NOT NULL DEFAULT 0,
    supply_gap_no_strong_incumbent INTEGER NOT NULL DEFAULT 0,
    supply_gap_no_recent_entrants INTEGER NOT NULL DEFAULT 0,
    supply_gap_unresolved_complaints INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'CANDIDATE',
    first_seen TEXT,
    last_seen TEXT
);

CREATE TABLE IF NOT EXISTS problem_evidence (
    evidence_id TEXT PRIMARY KEY,
    problem_id TEXT NOT NULL REFERENCES problems(problem_id),
    item_id INTEGER NOT NULL REFERENCES hn_items(id),
    author TEXT,
    excerpt TEXT
);

CREATE TABLE IF NOT EXISTS demand_scores (
    problem_id TEXT PRIMARY KEY REFERENCES problems(problem_id),
    independent_users_score INTEGER NOT NULL,
    persistence_score INTEGER NOT NULL,
    frequency_score INTEGER NOT NULL,
    risk_score INTEGER NOT NULL,
    manual_evidence_score INTEGER NOT NULL,
    purchase_intent_score INTEGER NOT NULL,
    source_diversity_score INTEGER NOT NULL,
    total INTEGER NOT NULL,
    independent_users INTEGER NOT NULL,
    passed INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS supply_candidates (
    product_id TEXT PRIMARY KEY,
    problem_id TEXT NOT NULL REFERENCES problems(problem_id),
    name TEXT NOT NULL,
    domain TEXT,
    dedupe_key TEXT NOT NULL,
    source TEXT NOT NULL,
    evidence_url TEXT,
    merged_into_product_id TEXT REFERENCES supply_candidates(product_id),
    common_crawl_excerpt TEXT
);

CREATE TABLE IF NOT EXISTS supply_verification (
    product_id TEXT PRIMARY KEY REFERENCES supply_candidates(product_id),
    signals TEXT NOT NULL,
    signal_count INTEGER NOT NULL,
    active INTEGER NOT NULL,
    supply_type TEXT NOT NULL,
    weight REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS opportunities (
    problem_id TEXT PRIMARY KEY REFERENCES problems(problem_id),
    demand_score INTEGER NOT NULL,
    effective_supply REAL NOT NULL,
    supply_scarcity_score INTEGER NOT NULL,
    scarcity_grade TEXT NOT NULL,
    priority_score REAL NOT NULL,
    confidence TEXT NOT NULL,
    decision TEXT NOT NULL,
    evidence_ids TEXT NOT NULL,
    product_ids TEXT NOT NULL,
    human_observation_count INTEGER NOT NULL DEFAULT 0,
    human_adjusted_supply_scarcity_score REAL,
    human_calibration_status TEXT NOT NULL DEFAULT 'NO_DATA',
    direct_competitor_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_reliability (
    source TEXT PRIMARY KEY,
    demand_problem_total INTEGER NOT NULL DEFAULT 0,
    demand_problem_passed INTEGER NOT NULL DEFAULT 0,
    demand_reliability_score REAL,
    demand_reliability_status TEXT NOT NULL DEFAULT 'NO_DATA',
    supply_candidate_total INTEGER NOT NULL DEFAULT 0,
    supply_candidate_active INTEGER NOT NULL DEFAULT 0,
    supply_reliability_score REAL,
    supply_reliability_status TEXT NOT NULL DEFAULT 'NO_DATA',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS titles (
    title TEXT NOT NULL,
    normalized TEXT NOT NULL,
    problem_id TEXT NOT NULL REFERENCES problems(problem_id),
    run_id TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL,
    google_title_footprint REAL,
    google_title_collision_class TEXT,
    human_title_validation_count INTEGER NOT NULL DEFAULT 0,
    title_collision_adjustment REAL NOT NULL DEFAULT 0.0,
    PRIMARY KEY (normalized, run_id)
);
"""


# CREATE TABLE IF NOT EXISTS only creates a table the first time local.db is
# built; it does not retroactively add columns to a table that already exists
# from an earlier schema revision. Each column added to an existing table
# after its initial release must be listed here too, or scripts touching a
# pre-existing local.db will hit "no such column" at runtime.
COLUMN_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("problems", "risk_severity", "TEXT NOT NULL DEFAULT 'none'"),
    ("problems", "purchase_intent", "TEXT NOT NULL DEFAULT 'none'"),
    ("problems", "has_manual_or_complaint_evidence", "INTEGER NOT NULL DEFAULT 0"),
    ("problems", "supply_gap_user_specific", "INTEGER NOT NULL DEFAULT 0"),
    ("problems", "supply_gap_no_strong_incumbent", "INTEGER NOT NULL DEFAULT 0"),
    ("problems", "supply_gap_no_recent_entrants", "INTEGER NOT NULL DEFAULT 0"),
    ("problems", "supply_gap_unresolved_complaints", "INTEGER NOT NULL DEFAULT 0"),
    ("demand_scores", "risk_score", "INTEGER NOT NULL DEFAULT 0"),
    ("opportunities", "human_observation_count", "INTEGER NOT NULL DEFAULT 0"),
    ("opportunities", "human_adjusted_supply_scarcity_score", "REAL"),
    ("opportunities", "human_calibration_status", "TEXT NOT NULL DEFAULT 'NO_DATA'"),
    # hn_items now also holds normalized gh_archive events (id ranges do not
    # overlap: HN item ids are still in the tens of millions as of 2026, GH
    # issue/comment entity ids are already in the billions - see
    # gh_archive_client.normalize_event). "source" distinguishes the two for
    # evidence traceability; it does not gate any query.
    ("hn_items", "source", "TEXT NOT NULL DEFAULT 'hacker_news'"),
    ("titles", "google_title_footprint", "REAL"),
    ("titles", "google_title_collision_class", "TEXT"),
    ("titles", "human_title_validation_count", "INTEGER NOT NULL DEFAULT 0"),
    ("titles", "title_collision_adjustment", "REAL NOT NULL DEFAULT 0.0"),
    ("opportunities", "direct_competitor_count", "INTEGER NOT NULL DEFAULT 0"),
    ("supply_candidates", "merged_into_product_id", "TEXT"),
    ("supply_candidates", "common_crawl_excerpt", "TEXT"),
)


def connect(project_root: Path) -> sqlite3.Connection:
    db_path = project_root / "data" / "local.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _apply_column_migrations(conn)
    conn.commit()


def _apply_column_migrations(conn: sqlite3.Connection) -> None:
    for table, column, ddl in COLUMN_MIGRATIONS:
        existing_columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in existing_columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
