"""후보 문장을 문자열 유사도로 1차 군집화하고 애매한 군집을 표시한다."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from saas_words_two import clustering, db, ids
from saas_words_two.contracts import atomic_write_text


def load_candidates(conn) -> list[clustering.Candidate]:
    rows = conn.execute(
        "SELECT cs.id AS candidate_id, cs.item_id AS item_id, cs.sentence AS sentence, "
        "hi.by AS author "
        "FROM candidate_sentences cs JOIN hn_items hi ON hi.id = cs.item_id "
        "ORDER BY cs.id"
    ).fetchall()
    return [
        clustering.Candidate(
            candidate_id=row["candidate_id"],
            item_id=row["item_id"],
            sentence=row["sentence"],
            author=row["author"],
        )
        for row in rows
    ]


def clusters_to_json(clusters: list[clustering.Cluster], generated_at: str) -> dict:
    return {
        "generated_at": generated_at,
        "clusters": [
            {
                "cluster_id": cluster.cluster_id,
                "confident": cluster.confident,
                "ambiguous": cluster.ambiguous,
                "independent_user_count": cluster.independent_user_count,
                "members": [
                    {
                        "candidate_id": member.candidate_id,
                        "item_id": member.item_id,
                        "author": member.author,
                        "sentence": member.sentence,
                    }
                    for member in cluster.members
                ],
            }
            for cluster in clusters
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="defaults to <project-root>/output/intermediate/problem_clusters.json",
    )
    args = parser.parse_args(argv)

    project_root = args.project_root
    output_path = args.output or project_root / "output" / "intermediate" / "problem_clusters.json"

    conn = db.connect(project_root)
    try:
        candidates = load_candidates(conn)
    finally:
        conn.close()

    clusters = clustering.cluster_candidates(candidates)
    generated_at = ids.now_kst().isoformat()
    atomic_write_text(
        output_path, json.dumps(clusters_to_json(clusters, generated_at), indent=2, ensure_ascii=False) + "\n"
    )

    confident = sum(1 for c in clusters if c.confident and len(c.members) > 1)
    ambiguous = sum(1 for c in clusters if c.ambiguous)
    singletons = sum(1 for c in clusters if len(c.members) == 1)
    print(
        f"CLUSTERING: candidates={len(candidates)} clusters={len(clusters)} "
        f"confident_multi={confident} ambiguous={ambiguous} singletons={singletons}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
