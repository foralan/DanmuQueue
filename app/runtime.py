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


