from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from .config import CONFIG_PATH, AppConfig, load_config, select_danmaku_mode
from .danmaku import build_client, run_client_until_cancelled
from .events import DanmakuEvent
from .queue import QueueCore
from .runtime import RuntimeState
from .ws import WsHub


class AppContext:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.config_path = project_root / CONFIG_PATH
        self.cfg: AppConfig = load_config(self.config_path)

        self.runtime = RuntimeState(
            status="stopped",
            test_enabled=bool(self.cfg.runtime.test_enabled),
            danmaku_status="idle",
        )

        self.queue = QueueCore()
        self.ws = WsHub()
        self._lock = asyncio.Lock()

        self._event_q: asyncio.Queue[DanmakuEvent] = asyncio.Queue(maxsize=200)
        self._consumer_task: asyncio.Task[None] | None = None

        # danmaku worker task placeholder (implemented in danmaku-mode todo)
        self._danmaku_task: asyncio.Task[None] | None = None

    async def start_background_tasks(self) -> None:
        if self._consumer_task is None or self._consumer_task.done():
            self._consumer_task = asyncio.create_task(self._consumer_loop())

    async def shutdown(self) -> None:
        await self.stop_runtime()
        if self._consumer_task:
            self._consumer_task.cancel()

    async def put_event(self, ev: DanmakuEvent) -> None:
        await self._event_q.put(ev)

    async def process_event(self, ev: DanmakuEvent) -> tuple[bool, str]:
        """
        Process a danmaku event immediately using the same rules as the async consumer.

        Returns (changed, reason):
        - changed=True means queue state changed and should be broadcast
        - reason is one of: not_running|no_keyword|no_match|no_user_key|ok|duplicate|full
        """
        async with self._lock:
            if self.runtime.status != "running":
                return False, "not_running"

            keyword = (self.cfg.queue.keyword or "").strip()
            if not keyword:
                return False, "no_keyword"

            if keyword not in ev.msg:
                return False, "no_match"

            user_key = (ev.user_key or ev.uname).strip()
            if not user_key:
                return False, "no_user_key"

            changed, reason = self.queue.enqueue(
                user_key=user_key,
                uname=ev.uname,
                max_queue=self.cfg.queue.max_queue,
            )
            return changed, reason

    async def start_runtime(self) -> tuple[bool, str | None]:
        async with self._lock:
            mode, err = select_danmaku_mode(self.cfg)
            if err:
                self.runtime.danmaku_status = "error"
                self.runtime.danmaku_error = err
                return False, err

            self.runtime.status = "running"
            self.runtime.danmaku_status = "running"
            self.runtime.danmaku_error = None
            # Apply persisted toggle from config on start (user can pre-check before start).
            self.runtime.test_enabled = bool(self.cfg.runtime.test_enabled)

            await self._start_danmaku_locked(mode)

        await self.broadcast_state()
        return True, None

    async def stop_runtime(self) -> None:
        async with self._lock:
            self.runtime.status = "stopped"
            # Keep user's preference; it won't take effect until running again.
            self.runtime.test_enabled = bool(self.cfg.runtime.test_enabled)
            self.runtime.danmaku_status = "idle"
            self.runtime.danmaku_error = None

            if self._danmaku_task and not self._danmaku_task.done():
                self._danmaku_task.cancel()
            self._danmaku_task = None

        await self.broadcast_state()

    async def set_test_enabled(self, enabled: bool) -> tuple[bool, str | None]:
        async with self._lock:
            # Runtime-only toggle (config is only loaded on process start).
            self.runtime.test_enabled = bool(enabled)
        await self.broadcast_state()
        return True, None

    async def update_config(self, updater: Any) -> tuple[bool, str | None]:
        """
        updater: a callable (cfg)->cfg, returns new cfg.
        """
        async with self._lock:
            try:
                new_cfg = updater(self.cfg)
            except Exception as e:
                return False, str(e)
            self.cfg = new_cfg

            # If running, restart danmaku with new config.
            if self.runtime.status == "running":
                mode, err = select_danmaku_mode(self.cfg)
                if err:
                    self.runtime.danmaku_status = "error"
                    self.runtime.danmaku_error = err
                else:
                    await self._start_danmaku_locked(mode, restart=True)
            else:
                # If not running, still refresh danmaku status for UI display.
                mode, err = select_danmaku_mode(self.cfg)
                if err:
                    self.runtime.danmaku_status = "error"
                    self.runtime.danmaku_error = err
                else:
                    self.runtime.danmaku_status = "idle"
                    self.runtime.danmaku_error = None
        await self.broadcast_state()
        return True, None

    def overlay_url(self) -> str:
        return f"http://{self.cfg.server.host}:{self.cfg.server.port}/overlay"

    async def broadcast_state(self) -> None:
        await self.ws.broadcast(self.state_payload())

    def state_payload(self) -> dict[str, Any]:
        max_q = int(self.cfg.queue.max_queue)
        secret_mask = "********"
        return {
            "type": "state",
            "runtime": {
                "status": self.runtime.status,
                "test_enabled": self.runtime.test_enabled,
                "overlay_url": self.overlay_url(),
                "danmaku_status": self.runtime.danmaku_status,
                "danmaku_error": self.runtime.danmaku_error,
            },
            "config": {
                "server": {"host": self.cfg.server.host, "port": self.cfg.server.port},
                "queue": {"keyword": self.cfg.queue.keyword, "max_queue": max_q},
                "ui": {
                    "overlay_title": self.cfg.ui.overlay_title,
                    "current_title": self.cfg.ui.current_title,
                    "queue_title": self.cfg.ui.queue_title,
                    "marked_color": self.cfg.ui.marked_color,
                    "overlay_show_mark": self.cfg.ui.overlay_show_mark,
                },
                "style": {"custom_css_path": self.cfg.style.custom_css_path},
                "bilibili": {
                    "open_live": {
                        "access_key": self.cfg.bilibili.open_live.access_key,
                        "access_secret": secret_mask if self.cfg.bilibili.open_live.access_secret else "",
                        "app_id": self.cfg.bilibili.open_live.app_id,
                        "identity_code": self.cfg.bilibili.open_live.identity_code,
                    },
                    "web": {
                        "sessdata": secret_mask if self.cfg.bilibili.web.sessdata else "",
                        "room_id": self.cfg.bilibili.web.room_id,
                    },
                },
            },
            "queue": self.queue.state.to_dict(max_q),
        }

    async def _consumer_loop(self) -> None:
        while True:
            ev = await self._event_q.get()
            changed, _reason = await self.process_event(ev)
            if changed:
                await self.broadcast_state()

    # _handle_event removed; use process_event() for both async and sync paths.

    async def _start_danmaku_locked(self, mode: str, restart: bool = False) -> None:
        if restart and self._danmaku_task and not self._danmaku_task.done():
            self._danmaku_task.cancel()
            self._danmaku_task = None

        if self._danmaku_task and not self._danmaku_task.done():
            return

        rt = build_client(self.cfg, mode, self.put_event)

        async def runner() -> None:
            try:
                await run_client_until_cancelled(rt)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                async with self._lock:
                    self.runtime.danmaku_status = "error"
                    self.runtime.danmaku_error = f"danmaku crashed: {e!r}"
                    # keep running, but stop accepting new queue entries? (we keep running)
                await self.broadcast_state()

        self._danmaku_task = asyncio.create_task(runner())


