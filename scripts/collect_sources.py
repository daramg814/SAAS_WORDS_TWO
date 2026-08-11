"""데이터원 접근성 검사 결과에 따라 증분 수집한다."""

from __future__ import annotations

import argparse
from pathlib import Path

import requests

from saas_words_two import collection, config, db, ids, text_filter


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    project_root = args.project_root
    sources_config = config.load_sources_config(project_root)
    project_config = config.load_project_config(project_root)
    now = ids.now_kst()

    session = requests.Session()
    access_report = collection.run_access_test(
        project_root, sources_config, session, generated_at=now.isoformat()
    )
    if access_report.results.get("hacker_news", {}).get("status") != "PASS":
        print("SOURCE ACCESS: FAIL - hacker_news is required and did not pass")
        for name, info in access_report.results.items():
            print(f"  {name}: {info['status']} ({info['detail']})")
        return 2
    if not access_report.disk_usage["ok"]:
        print(
            "SOURCE ACCESS: FAIL - insufficient free disk space "
            f"({access_report.disk_usage['free_bytes']} bytes free, "
            f"minimum {collection.MIN_FREE_DISK_BYTES})"
        )
        return 3

    conn = db.connect(project_root)
    try:
        hn_settings = project_config["collection"]["hacker_news"]
        recency_summary = collection.run_incremental_collection(
            project_root, conn, sources_config, hn_settings, session, fetched_at=now.isoformat()
        )

        months_back = project_config["collection"]["recent_months_required"]
        cutoff_epoch = int(now.timestamp()) - months_back * 30 * 24 * 3600
        search_summary = collection.run_keyword_search_collection(
            conn,
            list(text_filter.PAIN_PATTERNS),
            session,
            hits_per_pattern=hn_settings["search_hits_per_pattern"],
            budget=hn_settings["search_max_items_per_run"],
            created_after_epoch=cutoff_epoch,
            fetched_at=now.isoformat(),
        )

        # DEMAND-001 follow-up (2026-08-11): a second, smaller keyword-search
        # pass using cross-industry process jargon (text_filter.INDUSTRY_TERMS)
        # instead of generic pain-framing phrases - quoted for exact-phrase
        # matching (real probes showed unquoted multi-common-word terms get
        # diluted by Algolia's fuzzy ranking). Reuses the same collection
        # function/dedup path as the PAIN_PATTERNS search above; only the
        # query list and budget differ.
        industry_term_summary = collection.run_keyword_search_collection(
            conn,
            [f'"{term}"' for term in text_filter.INDUSTRY_TERMS],
            session,
            hits_per_pattern=hn_settings["industry_term_hits_per_pattern"],
            budget=hn_settings["industry_term_search_max_items_per_run"],
            created_after_epoch=cutoff_epoch,
            fetched_at=now.isoformat(),
        )

        gh_summary = None
        if access_report.results.get("gh_archive", {}).get("status") == "PASS" and sources_config["sources"].get(
            "gh_archive", {}
        ).get("enabled"):
            gh_settings = project_config["collection"]["gh_archive"]
            gh_summary = collection.run_gh_archive_collection(
                project_root, conn, sources_config, gh_settings, session, now=now, fetched_at=now.isoformat()
            )

        se_summary = None
        if access_report.results.get("stack_exchange_dump", {}).get("status") == "PASS" and sources_config[
            "sources"
        ].get("stack_exchange_dump", {}).get("enabled"):
            se_settings = project_config["collection"]["stack_exchange_dump"]
            se_summary = collection.run_stack_exchange_collection(
                project_root, conn, sources_config, se_settings, session, fetched_at=now.isoformat()
            )

        feeds_summary = None
        feeds_conf = sources_config["sources"].get("official_feeds", {})
        if access_report.results.get("official_feeds", {}).get("status") == "PASS" and feeds_conf.get("enabled"):
            feeds_summary = collection.run_official_feeds_collection(
                conn, feeds_conf["feed_urls"], session, fetched_at=now.isoformat()
            )

        app_store_summary = None
        as_conf = sources_config["sources"].get("app_store_reviews", {})
        if access_report.results.get("app_store_reviews", {}).get("status") == "PASS" and as_conf.get("enabled"):
            # search_terms/apps_per_term/country (which apps to look at) live in
            # sources.yaml alongside the other per-source config; max_items_per_run
            # (how much to collect this run) lives in project.yaml like gh_archive's
            # max_hours_per_run / stack_exchange_dump's max_items_per_run.
            as_settings = {**as_conf, **project_config["collection"]["app_store_reviews"]}
            app_store_summary = collection.run_app_store_reviews_collection(
                conn, as_settings, session, fetched_at=now.isoformat()
            )
    finally:
        conn.close()

    print(
        f"COLLECTED (recency lists) stories={recency_summary.fetched_stories} "
        f"comments={recency_summary.fetched_comments} skipped_existing={recency_summary.skipped_existing} "
        f"cursor={recency_summary.cursor_before}->{recency_summary.cursor_after}"
    )
    print(
        f"COLLECTED (keyword search, {months_back}mo window) "
        f"stories={search_summary.fetched_stories} comments={search_summary.fetched_comments} "
        f"skipped_existing={search_summary.skipped_existing}"
    )
    print(
        f"COLLECTED (industry term search, {months_back}mo window) "
        f"stories={industry_term_summary.fetched_stories} comments={industry_term_summary.fetched_comments} "
        f"skipped_existing={industry_term_summary.skipped_existing}"
    )
    errors = list(recency_summary.errors) + list(search_summary.errors) + list(industry_term_summary.errors)
    if gh_summary is not None:
        print(
            f"COLLECTED (gh_archive) stories={gh_summary.fetched_stories} "
            f"comments={gh_summary.fetched_comments} skipped_existing={gh_summary.skipped_existing} "
            f"hours={len(gh_summary.hours_processed)} cursor={gh_summary.cursor_before}->{gh_summary.cursor_after}"
        )
        errors += gh_summary.errors
    if se_summary is not None:
        print(
            f"COLLECTED (stack_exchange_dump) stories={se_summary.fetched_stories} "
            f"comments={se_summary.fetched_comments} skipped_existing={se_summary.skipped_existing} "
            f"cursor={se_summary.cursor_before}->{se_summary.cursor_after}"
        )
        errors += se_summary.errors
    if feeds_summary is not None:
        print(
            f"COLLECTED (official_feeds) stories={feeds_summary.fetched_stories} "
            f"skipped_existing={feeds_summary.skipped_existing}"
        )
        errors += feeds_summary.errors
    if app_store_summary is not None:
        print(
            f"COLLECTED (app_store_reviews) stories={app_store_summary.fetched_stories} "
            f"apps_seen={app_store_summary.apps_seen} skipped_existing={app_store_summary.skipped_existing}"
        )
        errors += app_store_summary.errors
    for error in errors:
        print(f"  WARN: {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
