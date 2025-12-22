from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DanmakuEvent:
    uname: str
    msg: str
    user_key: str | None = None
    source: str = "unknown"  # web|open_live|test


