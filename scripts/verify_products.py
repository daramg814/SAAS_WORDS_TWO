"""판정된 활성 신호·공급 유형으로부터 활성 여부와 유효 공급 가중치를 계산한다."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from saas_words_two import db, supply

VALID_SUPPLY_TYPES = tuple(supply.SUPPLY_TYPE_WEIGHTS.keys())


def record_verification(conn, product_id: str, signals: dict[str, bool], supply_type: str) -> None:
    if supply_type not in VALID_SUPPLY_TYPES:
        raise ValueError(f"unknown supply_type: {supply_type}")
    conn.execute(
        "INSERT INTO supply_verification (product_id, signals, signal_count, active, supply_type, weight) "
        "VALUES (?, ?, 0, 0, ?, 0.0) "
        "ON CONFLICT(product_id) DO UPDATE SET signals=excluded.signals, supply_type=excluded.supply_type",
        (product_id, json.dumps(signals, sort_keys=True), supply_type),
    )


def finalize_verifications(conn) -> int:
    rows = conn.execute("SELECT product_id, signals, supply_type FROM supply_verification").fetchall()
    for row in rows:
        signals = json.loads(row["signals"])
        signal_count = supply.active_signal_count(signals)
        active = supply.is_active_supply(signals)
        weight = supply.SUPPLY_TYPE_WEIGHTS.get(row["supply_type"], 0.0) if active else 0.0
        conn.execute(
            "UPDATE supply_verification SET signal_count = ?, active = ?, weight = ? WHERE product_id = ?",
            (signal_count, int(active), weight, row["product_id"]),
        )
    conn.commit()
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    conn = db.connect(args.project_root)
    try:
        total = finalize_verifications(conn)
        active_count = conn.execute(
            "SELECT COUNT(*) c FROM supply_verification WHERE active = 1"
        ).fetchone()["c"]
    finally:
        conn.close()

    print(f"PRODUCT VERIFICATION: total={total} active={active_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
