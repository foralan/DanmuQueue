from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


RuntimeStatus = Literal["stopped", "running"]


@dataclass
class RuntimeState:
    status: RuntimeStatus = "stopped"
    test_enabled: bool = False

    danmaku_status: str = "idle"  # idle|running|error
    danmaku_error: str | None = None
    active_mode: str | None = None

    # Queue control
    queue_paused: bool = False
    queue_pause_reason: str | None = None
    queue_auto_pause_time: str = ""  # "HH:MM"
    queue_pause_until_ts: float | None = None  # resolved to timestamp for today
    queue_pause_check_interval: int = 60


