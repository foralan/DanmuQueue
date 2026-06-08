from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass
class QueueItem:
    user_key: str  # open_id / uid / fallback uname
    uname: str
    marked: bool = False
    priority: bool = False
    joined_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_key": self.user_key,
            "uname": self.uname,
            "marked": self.marked,
            "priority": self.priority,
            "joined_at": self.joined_at,
        }


class QueueState:
    """
    0号 = current
    1..n = waiting

    max_queue limits total (current + waiting)
    """

    def __init__(self) -> None:
        self.current: QueueItem | None = None
        self.waiting: list[QueueItem] = []

    def total_len(self) -> int:
        return (1 if self.current else 0) + len(self.waiting)

    def has_user(self, user_key: str) -> bool:
        if self.current and self.current.user_key == user_key:
            return True
        return any(it.user_key == user_key for it in self.waiting)

    def to_list(self) -> list[QueueItem]:
        out: list[QueueItem] = []
        if self.current:
            out.append(self.current)
        out.extend(self.waiting)
        return out

    def to_dict(self, max_queue: int) -> dict[str, Any]:
        items = self.to_list()
        return {
            "items": [it.to_dict() for it in items],
            "max_queue": max_queue,
            "total": len(items),
            "is_full": len(items) >= max_queue,
        }


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class QueueCore:
    def __init__(self) -> None:
        self.state = QueueState()

    def enqueue(self, *, user_key: str, uname: str, max_queue: int) -> tuple[bool, str]:
        if self.state.has_user(user_key):
            return False, "duplicate"
        if self.state.total_len() >= max_queue:
            return False, "full"

        item = QueueItem(user_key=user_key, uname=uname, joined_at=now_iso())
        if self.state.current is None:
            self.state.current = item
        else:
            self.state.waiting.append(item)
        return True, "ok"

    def remove(self, user_key: str) -> bool:
        if self.state.current and self.state.current.user_key == user_key:
            self.state.current = None
            if self.state.waiting:
                self.state.current = self.state.waiting.pop(0)
            return True

        for i, it in enumerate(self.state.waiting):
            if it.user_key == user_key:
                self.state.waiting.pop(i)
                return True
        return False

    def pin_top(self, user_key: str) -> bool:
        # Promote a normal waiting user into the priority segment. Current and
        # already-priority users keep their positions.
        if self.state.current and self.state.current.user_key == user_key:
            return False
        idx = next((i for i, it in enumerate(self.state.waiting) if it.user_key == user_key), None)
        if idx is None:
            return False
        if self.state.waiting[idx].priority:
            return False
        it = self.state.waiting.pop(idx)
        it.priority = True
        priority_tail = self._priority_tail_index()
        if idx < priority_tail:
            priority_tail -= 1
        self.state.waiting.insert(priority_tail, it)
        return True

    def priority_enqueue(self, *, user_key: str, uname: str) -> tuple[bool, str]:
        if self.state.current and self.state.current.user_key == user_key:
            return False, "current"

        priority_tail = self._priority_tail_index()
        for i, it in enumerate(self.state.waiting):
            if it.user_key != user_key:
                continue
            if it.priority:
                return False, "duplicate_priority"
            it.priority = True
            it.uname = uname
            self.state.waiting.pop(i)
            if i < priority_tail:
                priority_tail -= 1
            self.state.waiting.insert(priority_tail, it)
            return True, "promoted_priority"

        item = QueueItem(user_key=user_key, uname=uname, priority=True, joined_at=now_iso())
        if self.state.current is None:
            self.state.current = item
        else:
            self.state.waiting.insert(priority_tail, item)
        return True, "priority_ok"

    def _priority_tail_index(self) -> int:
        for i, it in enumerate(self.state.waiting):
            if not it.priority:
                return i
        return len(self.state.waiting)

    def set_marked(self, user_key: str, marked: bool) -> bool:
        if self.state.current and self.state.current.user_key == user_key:
            self.state.current.marked = marked
            return True
        for i, it in enumerate(self.state.waiting):
            if it.user_key == user_key:
                it.marked = marked
                if marked and it.priority:
                    self.state.waiting.pop(i)
                    self.state.waiting.insert(0, it)
                return True
        return False
