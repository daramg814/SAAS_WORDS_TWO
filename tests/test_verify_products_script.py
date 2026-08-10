import sys
from pathlib import Path

import pytest

from saas_words_two import db

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import verify_products


def seed_candidate(conn, product_id="S-0001"):
    conn.execute(
        "INSERT INTO problems (problem_id, status) VALUES ('P-0001', 'DEMAND_PASSED')"
    )
    conn.execute(
        "INSERT INTO supply_candidates (product_id, problem_id, name, dedupe_key, source) "
        "VALUES (?, 'P-0001', 'VendorGuard', 'vendorguard', 'hn_show')",
        (product_id,),
    )
    conn.commit()


def test_record_verification_rejects_unknown_supply_type(tmp_path):
    conn = db.connect(tmp_path)
    seed_candidate(conn)
    with pytest.raises(ValueError):
        verify_products.record_verification(conn, "S-0001", {"official_name": True}, "bogus")
    conn.close()


def test_finalize_verifications_computes_active_and_weight(tmp_path):
    conn = db.connect(tmp_path)
    seed_candidate(conn)
    signals = {
        "official_name": True,
        "target_user": True,
        "core_feature": True,
        "signup_or_demo": False,
        "pricing": False,
        "recent_activity": False,
        "product_docs": False,
        "customer_references": False,
    }
    verify_products.record_verification(conn, "S-0001", signals, "direct")
    conn.commit()

    processed = verify_products.finalize_verifications(conn)
    assert processed == 1

    row = conn.execute("SELECT * FROM supply_verification WHERE product_id = 'S-0001'").fetchone()
    assert row["signal_count"] == 3
    assert row["active"] == 1
    assert row["weight"] == 1.0
    conn.close()


def test_finalize_verifications_zero_weight_when_inactive(tmp_path):
    conn = db.connect(tmp_path)
    seed_candidate(conn)
    verify_products.record_verification(
        conn, "S-0001", {"official_name": True, "target_user": False}, "direct"
    )
    conn.commit()
    verify_products.finalize_verifications(conn)

    row = conn.execute("SELECT * FROM supply_verification WHERE product_id = 'S-0001'").fetchone()
    assert row["active"] == 0
    assert row["weight"] == 0.0
    conn.close()


def test_record_verification_is_idempotent_on_rerun(tmp_path):
    conn = db.connect(tmp_path)
    seed_candidate(conn)
    verify_products.record_verification(conn, "S-0001", {"official_name": True}, "direct")
    verify_products.record_verification(conn, "S-0001", {"official_name": True, "target_user": True}, "partial")
    conn.commit()
    rows = conn.execute("SELECT COUNT(*) c FROM supply_verification").fetchone()
    assert rows["c"] == 1
    row = conn.execute("SELECT supply_type FROM supply_verification").fetchone()
    assert row["supply_type"] == "partial"
    conn.close()


def test_main_reports_counts(tmp_path, capsys):
    conn = db.connect(tmp_path)
    seed_candidate(conn)
    verify_products.record_verification(
        conn,
        "S-0001",
        {"official_name": True, "target_user": True, "core_feature": True},
        "direct",
    )
    conn.commit()
    conn.close()

    exit_code = verify_products.main(["--project-root", str(tmp_path)])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "total=1" in out
    assert "active=1" in out
