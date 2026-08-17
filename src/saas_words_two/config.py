from __future__ import annotations

from pathlib import Path

import yaml


def load_project_config(project_root: Path) -> dict:
    return yaml.safe_load((project_root / "config" / "project.yaml").read_text(encoding="utf-8"))


def load_sources_config(project_root: Path) -> dict:
    return yaml.safe_load((project_root / "config" / "sources.yaml").read_text(encoding="utf-8"))


def load_keyword_metrics_config(project_root: Path) -> dict:
    """avg_monthly_searches_min/competition_index_exact 필터 기준값과 Google Ads
    API 런타임 설정 (memory/ACTIVE_ISSUES.md GKP-001). 이 파일의 두 기준값만
    바꾸면 필터 동작이 바뀐다 - 코드는 이 값을 읽기만 한다."""
    return yaml.safe_load((project_root / "config" / "keyword_metrics.yaml").read_text(encoding="utf-8"))
