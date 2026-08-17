from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def now_kst() -> datetime:
    return datetime.now(KST)


def format_run_id(mode: str, when: datetime) -> str:
    prefix = "QA" if mode == "qa" else "RUN"
    return f"{prefix}-{when.strftime('%Y%m%d-%H%M%S')}-KST"
