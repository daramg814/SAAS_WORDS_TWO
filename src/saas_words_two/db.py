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
    fetched_at TEXT NOT NULL
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
    frequency TEXT,
    purchase_intent INTEGER NOT NULL DEFAULT 0,
    economic_loss INTEGER NOT NULL DEFAULT 0,
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
    loss_score INTEGER NOT NULL,
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
    evidence_url TEXT
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
    PRIMARY KEY (normalized, run_id)
);
"""


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
    conn.commit()
