from __future__ import annotations

from pathlib import Path

import yaml


def load_project_config(project_root: Path) -> dict:
    return yaml.safe_load((project_root / "config" / "project.yaml").read_text(encoding="utf-8"))


def load_sources_config(project_root: Path) -> dict:
    return yaml.safe_load((project_root / "config" / "sources.yaml").read_text(encoding="utf-8"))
