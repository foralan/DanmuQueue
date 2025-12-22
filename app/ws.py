from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import WebSocket


class WsHub:
    def __init__(self) -> None:
        self._conns: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def add(self, ws: WebSocket) -> None:
        async with self._lock:
            self._conns.add(ws)

    async def remove(self, ws: WebSocket) -> None:
        async with self._lock:
            self._conns.discard(ws)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        msg = json.dumps(payload, ensure_ascii=False)
        async with self._lock:
            conns = list(self._conns)
        if not conns:
            return
        await asyncio.gather(*(self._safe_send(ws, msg) for ws in conns), return_exceptions=True)

    async def _safe_send(self, ws: WebSocket, msg: str) -> None:
        try:
            await ws.send_text(msg)
        except Exception:
            await self.remove(ws)


