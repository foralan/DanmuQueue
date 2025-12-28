from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta
from dataclasses import replace
from pathlib import Path
from typing import Any

from .bili_utils import fetch_sessdata_from_browser, verify_sessdata
from .config import CONFIG_PATH, AppConfig, DanmakuMode, load_config, select_danmaku_mode
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
            active_mode=None,
            queue_paused=False,
            queue_pause_reason=None,
            queue_auto_pause_time=str(self.cfg.queue.auto_pause_time),
            queue_pause_until_ts=None,
            queue_pause_check_interval=int(self.cfg.queue.pause_check_interval_seconds or 60),
        )

        self.queue = QueueCore()
        self.ws = WsHub()
        self._lock = asyncio.Lock()

        self._event_q: asyncio.Queue[DanmakuEvent] = asyncio.Queue(maxsize=200)
        self._consumer_task: asyncio.Task[None] | None = None

        # danmaku worker task placeholder (implemented in danmaku-mode todo)
        self._danmaku_task: asyncio.Task[None] | None = None
        self._pause_checker_task: asyncio.Task[None] | None = None

    async def start_background_tasks(self) -> None:
        if self._consumer_task is None or self._consumer_task.done():
            self._consumer_task = asyncio.create_task(self._consumer_loop())
        if self._pause_checker_task is None or self._pause_checker_task.done():
            self._pause_checker_task = asyncio.create_task(self._pause_checker_loop())

    async def shutdown(self) -> None:
        await self.stop_runtime()
        if self._consumer_task:
            self._consumer_task.cancel()
        if self._pause_checker_task:
            self._pause_checker_task.cancel()

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
            if self.runtime.queue_paused:
                return False, "paused"

            keyword = (self.cfg.queue.keyword or "").strip()
            if not keyword:
                return False, "no_keyword"

            msg = (ev.msg or "").strip()
            mode = self.cfg.queue.match_mode
            if mode == "exact":
                if msg != keyword:
                    return False, "no_match"
            else:
                # contains
                if keyword not in msg:
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
            effective_cfg, mode, err = await self._prepare_runtime_config()
            if err:
                self.runtime.danmaku_status = "error"
                self.runtime.danmaku_error = err
                self.runtime.active_mode = None
                return False, err

            self.runtime.status = "running"
            self.runtime.danmaku_status = "running"
            self.runtime.danmaku_error = None
            self.runtime.active_mode = mode
            # Apply persisted toggle from config on start (user can pre-check before start).
            self.runtime.test_enabled = bool(self.cfg.runtime.test_enabled)
            # Reset queue pause state on start
            self.runtime.queue_paused = False
            self.runtime.queue_pause_reason = None
            self.runtime.queue_auto_pause_time = str(self.cfg.queue.auto_pause_time)
            self.runtime.queue_pause_check_interval = int(self.cfg.queue.pause_check_interval_seconds or 60)
            self._reset_auto_pause_timer_locked()

            await self._start_danmaku_locked(effective_cfg, mode)

        await self.broadcast_state()
        return True, None

    async def stop_runtime(self) -> None:
        async with self._lock:
            self.runtime.status = "stopped"
            # Keep user's preference; it won't take effect until running again.
            self.runtime.test_enabled = bool(self.cfg.runtime.test_enabled)
            self.runtime.danmaku_status = "idle"
            self.runtime.danmaku_error = None
            self.runtime.active_mode = None
            self.runtime.queue_paused = False
            self.runtime.queue_pause_reason = None
            self.runtime.queue_pause_until_ts = None
            self.runtime.queue_auto_pause_time = str(self.cfg.queue.auto_pause_time)

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
            # Keep runtime fields in sync with latest config defaults.
            self.runtime.queue_pause_check_interval = int(self.cfg.queue.pause_check_interval_seconds or 60)
            self.runtime.queue_auto_pause_time = str(self.cfg.queue.auto_pause_time)

            # If running, restart danmaku with new config.
            if self.runtime.status == "running":
                effective_cfg, mode, err = await self._prepare_runtime_config()
                if err:
                    self.runtime.danmaku_status = "error"
                    self.runtime.danmaku_error = err
                    self.runtime.active_mode = None
                else:
                    self.runtime.active_mode = mode
                    await self._start_danmaku_locked(effective_cfg, mode, restart=True)
            else:
                # If not running, still refresh danmaku status for UI display.
                mode, err = select_danmaku_mode(self.cfg)
                if err:
                    self.runtime.danmaku_status = "error"
                    self.runtime.danmaku_error = err
                else:
                    self.runtime.danmaku_status = "idle"
                    self.runtime.danmaku_error = None
                    self.runtime.active_mode = None
        await self.broadcast_state()
        return True, None

    def overlay_url(self) -> str:
        return f"http://{self.cfg.server.host}:{self.cfg.server.port}/overlay"

    async def broadcast_state(self) -> None:
        await self.ws.broadcast(self.state_payload())

    def state_payload(self) -> dict[str, Any]:
        max_q = int(self.cfg.queue.max_queue)
        secret_mask = "********"
        queue_state = self.queue.state.to_dict(max_q)
        queue_state.update(
            {
                "paused": self.runtime.queue_paused,
                "pause_reason": self.runtime.queue_pause_reason,
                "pause_message": self.cfg.queue.pause_message,
                "auto_pause_time": self.runtime.queue_auto_pause_time,
            }
        )
        return {
            "type": "state",
            "runtime": {
                "status": self.runtime.status,
                "test_enabled": self.runtime.test_enabled,
                "overlay_url": self.overlay_url(),
                "danmaku_status": self.runtime.danmaku_status,
                "danmaku_error": self.runtime.danmaku_error,
                "active_mode": self.runtime.active_mode,
                "queue_paused": self.runtime.queue_paused,
                "queue_pause_reason": self.runtime.queue_pause_reason,
                "queue_auto_pause_time": self.runtime.queue_auto_pause_time,
                "queue_pause_until_ts": self.runtime.queue_pause_until_ts,
            },
            "config": {
                "server": {"host": self.cfg.server.host, "port": self.cfg.server.port},
                "queue": {
                    "keyword": self.cfg.queue.keyword,
                    "max_queue": max_q,
                    "match_mode": self.cfg.queue.match_mode,
                    "pause_message": self.cfg.queue.pause_message,
                    "auto_pause_time": self.cfg.queue.auto_pause_time,
                    "pause_check_interval_seconds": self.cfg.queue.pause_check_interval_seconds,
                },
                "ui": {
                    "overlay_title": self.cfg.ui.overlay_title,
                    "current_title": self.cfg.ui.current_title,
                    "queue_title": self.cfg.ui.queue_title,
                    "empty_text": self.cfg.ui.empty_text,
                    "marked_color": self.cfg.ui.marked_color,
                    "overlay_show_mark": self.cfg.ui.overlay_show_mark,
                },
                "style": {"custom_css_path": self.cfg.style.custom_css_path},
                "bilibili": {
                    "mode": getattr(self.cfg.bilibili, "mode", "auto"),
                    "open_live": {
                        "access_key": self.cfg.bilibili.open_live.access_key,
                        "access_secret": secret_mask if self.cfg.bilibili.open_live.access_secret else "",
                        "app_id": self.cfg.bilibili.open_live.app_id,
                        "identity_code": self.cfg.bilibili.open_live.identity_code,
                    },
                    "web": {
                        "sessdata": secret_mask if self.cfg.bilibili.web.sessdata else "",
                        "room_id": self.cfg.bilibili.web.room_id,
                        "auto_fetch_cookie": self.cfg.bilibili.web.auto_fetch_cookie,
                    },
                },
            },
            "queue": queue_state,
        }

    async def _consumer_loop(self) -> None:
        while True:
            ev = await self._event_q.get()
            changed, _reason = await self.process_event(ev)
            if changed:
                await self.broadcast_state()

    # _handle_event removed; use process_event() for both async and sync paths.

    async def _start_danmaku_locked(self, cfg: AppConfig, mode: str, restart: bool = False) -> None:
        if restart and self._danmaku_task and not self._danmaku_task.done():
            self._danmaku_task.cancel()
            self._danmaku_task = None

        if self._danmaku_task and not self._danmaku_task.done():
            return

        rt = build_client(cfg, mode, self.put_event)

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

    async def set_queue_paused(self, paused: bool, reason: str | None = None) -> tuple[bool, str | None]:
        async with self._lock:
            if paused:
                self.runtime.queue_paused = True
                self.runtime.queue_pause_reason = reason or "手动暂停"
                self.runtime.queue_pause_until_ts = None
            else:
                self.runtime.queue_paused = False
                self.runtime.queue_pause_reason = None
                self._reset_auto_pause_timer_locked()
        await self.broadcast_state()
        return True, None

    async def set_auto_pause_time(self, time_str: str) -> tuple[bool, str | None]:
        time_str = (time_str or "").strip()
        if time_str and not _is_valid_hhmm(time_str):
            return False, "auto_pause_time must be HH:MM (00-23:00-59)"
        async with self._lock:
            self.runtime.queue_auto_pause_time = time_str
            if self.runtime.queue_paused:
                self.runtime.queue_pause_until_ts = None
            else:
                self._reset_auto_pause_timer_locked()
        await self.broadcast_state()
        return True, None

    def _reset_auto_pause_timer_locked(self) -> None:
        self.runtime.queue_pause_until_ts = _next_timestamp_for_time_str(self.runtime.queue_auto_pause_time)

    def _maybe_auto_pause_locked(self) -> bool:
        """
        Returns True if state changed.
        """
        if self.runtime.status != "running":
            return False
        if self.runtime.queue_paused:
            return False
        if not self.runtime.queue_auto_pause_time:
            return False
        if self.runtime.queue_pause_until_ts is None:
            self.runtime.queue_pause_until_ts = _next_timestamp_for_time_str(self.runtime.queue_auto_pause_time)
            if self.runtime.queue_pause_until_ts is None:
                return False

        if time.time() >= self.runtime.queue_pause_until_ts:
            self.runtime.queue_paused = True
            self.runtime.queue_pause_reason = "自动暂停"
            self.runtime.queue_pause_until_ts = None
            return True
        return False

    async def _pause_checker_loop(self) -> None:
        while True:
            try:
                interval = int(self.runtime.queue_pause_check_interval or self.cfg.queue.pause_check_interval_seconds or 60)
                if interval <= 0:
                    interval = 60
                await asyncio.sleep(interval)
                changed = False
                async with self._lock:
                    changed = self._maybe_auto_pause_locked()
                if changed:
                    await self.broadcast_state()
            except asyncio.CancelledError:
                return
            except Exception:
                # swallow errors, keep loop alive
                continue


    async def _prepare_runtime_config(self) -> tuple[AppConfig | None, DanmakuMode | None, str | None]:
        """
        Returns (effective_cfg, mode, error).
        - If auto_fetch_cookie is enabled, load SESSDATA from local browsers (non-persisted).
        - For web mode, verifies SESSDATA before starting.
        """
        cfg = self.cfg
        web = cfg.bilibili.web
        sessdata = web.sessdata
        if web.auto_fetch_cookie:
            sessdata, err = fetch_sessdata_from_browser()
            if err:
                return None, None, err

        # Build an effective config used only for this runtime start.
        web_cfg = replace(web, sessdata=sessdata)
        bili_cfg = replace(cfg.bilibili, web=web_cfg)
        effective_cfg = replace(cfg, bilibili=bili_cfg)

        mode, err = select_danmaku_mode(effective_cfg)
        if err:
            return None, None, err

        if mode == "web":
            ok, msg = await verify_sessdata(sessdata)
            if not ok:
                return None, None, msg

        return effective_cfg, mode, None

    def fetch_browser_sessdata(self) -> tuple[str | None, str | None]:
        return fetch_sessdata_from_browser()


def _is_valid_hhmm(s: str) -> bool:
    if len(s) != 5 or s[2] != ":":
        return False
    hh, mm = s.split(":", 1)
    if not (hh.isdigit() and mm.isdigit()):
        return False
    h = int(hh)
    m = int(mm)
    return 0 <= h <= 23 and 0 <= m <= 59


def _next_timestamp_for_time_str(time_str: str) -> float | None:
    if not time_str or not _is_valid_hhmm(time_str):
        return None
    hh, mm = map(int, time_str.split(":", 1))
    now = datetime.now()
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return target.timestamp()


