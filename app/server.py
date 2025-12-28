from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, Response

from .assets import DEFAULT_CSS
from .bootstrap import ensure_first_run_files
from .config import (
    CONFIG_PATH,
    AppConfig,
    BiliConfig,
    OpenLiveConfig,
    QueueConfig,
    RuntimeConfig,
    ServerConfig,
    StyleConfig,
    UiConfig,
    WebDanmakuConfig,
    save_config,
)
from .context import AppContext
from .events import DanmakuEvent
from .models import (
    ConfigUpdateIn,
    QueueAutoPauseIn,
    QueuePinTopIn,
    QueueRemoveIn,
    QueuePauseIn,
    QueueToggleMarkIn,
    RuntimeTestEnableIn,
    TestDanmakuIn,
)
from .paths import static_dir as get_static_dir


def build_app(
    project_root: Path, *, restart_event: asyncio.Event | None = None, exit_event: asyncio.Event | None = None
) -> FastAPI:
    ensure_first_run_files(project_root)
    app = FastAPI()
    ctx = AppContext(project_root)
    app.state.ctx = ctx
    app.state.restart_event = restart_event
    app.state.exit_event = exit_event

    static_dir = get_static_dir(project_root)

    @app.on_event("startup")
    async def _startup() -> None:
        await ctx.start_background_tasks()
        # Always start in stopped state (no auto-start).

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await ctx.shutdown()

    def _page(name: str) -> FileResponse:
        p = static_dir / name
        if not p.exists():
            raise HTTPException(status_code=500, detail=f"missing static file: {name}")
        return FileResponse(p)

    @app.get("/admin", response_class=HTMLResponse)
    async def admin_page() -> Any:
        return _page("admin.html")

    @app.get("/overlay", response_class=HTMLResponse)
    async def overlay_page() -> Any:
        return _page("overlay.html")

    @app.get("/test", response_class=HTMLResponse)
    async def test_page() -> Any:
        return _page("test.html")

    @app.get("/static/default.css")
    async def default_css() -> Response:
        return Response(
            content=DEFAULT_CSS,
            media_type="text/css; charset=utf-8",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/static/custom.css")
    async def custom_css() -> Response:
        css_path = Path(ctx.cfg.style.custom_css_path).expanduser()
        if not css_path.is_absolute():
            css_path = project_root / css_path
        if not css_path.exists():
            return Response(content="", media_type="text/css; charset=utf-8", headers={"Cache-Control": "no-store"})
        return Response(
            content=css_path.read_text(encoding="utf-8"),
            media_type="text/css; charset=utf-8",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/state")
    async def api_state() -> dict[str, Any]:
        return ctx.state_payload()

    @app.post("/api/runtime/start")
    async def api_runtime_start() -> dict[str, Any]:
        ok, err = await ctx.start_runtime()
        if not ok:
            raise HTTPException(status_code=400, detail=err or "failed")
        return ctx.state_payload()

    @app.post("/api/runtime/stop")
    async def api_runtime_stop() -> dict[str, Any]:
        await ctx.stop_runtime()
        return ctx.state_payload()

    @app.post("/api/runtime/exit")
    async def api_runtime_exit() -> dict[str, Any]:
        # Best-effort graceful shutdown:
        # - stop runtime/danmaku
        # - tell supervisor loop to terminate uvicorn + exit process
        await ctx.stop_runtime()
        if app.state.exit_event is not None:
            app.state.exit_event.set()
        return {"ok": True}

    @app.post("/api/runtime/test_enable")
    async def api_runtime_test_enable(body: RuntimeTestEnableIn) -> dict[str, Any]:
        ok, err = await ctx.set_test_enabled(body.enabled)
        if not ok:
            raise HTTPException(status_code=400, detail=err or "failed")
        return ctx.state_payload()

    @app.post("/api/config")
    async def api_config_update(body: ConfigUpdateIn) -> dict[str, Any]:
        # Config is only loaded on process start. Saving config triggers an in-process restart.
        cfg = ctx.cfg
        server = cfg.server
        queue = cfg.queue
        ui = cfg.ui
        style = cfg.style
        bili = cfg.bilibili

        if body.host is not None:
            server = ServerConfig(host=body.host, port=server.port)
        if body.port is not None:
            server = ServerConfig(host=server.host, port=int(body.port))

        if body.keyword is not None:
            queue = QueueConfig(
                keyword=body.keyword,
                max_queue=queue.max_queue,
                match_mode=queue.match_mode,
                pause_message=queue.pause_message,
                auto_pause_time=queue.auto_pause_time,
                pause_check_interval_seconds=queue.pause_check_interval_seconds,
            )
        if body.max_queue is not None:
            queue = QueueConfig(
                keyword=queue.keyword,
                max_queue=int(body.max_queue),
                match_mode=queue.match_mode,
                pause_message=queue.pause_message,
                auto_pause_time=queue.auto_pause_time,
                pause_check_interval_seconds=queue.pause_check_interval_seconds,
            )
        if body.match_mode is not None:
            mm = str(body.match_mode).strip().lower()
            if mm not in ("exact", "contains"):
                raise HTTPException(status_code=400, detail="queue.match_mode must be 'exact' or 'contains'")
            queue = QueueConfig(
                keyword=queue.keyword,
                max_queue=queue.max_queue,
                match_mode=mm,
                pause_message=queue.pause_message,
                auto_pause_time=queue.auto_pause_time,
                pause_check_interval_seconds=queue.pause_check_interval_seconds,
            )
        if body.pause_message is not None:
            queue = QueueConfig(
                keyword=queue.keyword,
                max_queue=queue.max_queue,
                match_mode=queue.match_mode,
                pause_message=body.pause_message,
                auto_pause_time=queue.auto_pause_time,
                pause_check_interval_seconds=queue.pause_check_interval_seconds,
            )
        if body.auto_pause_time is not None:
            queue = QueueConfig(
                keyword=queue.keyword,
                max_queue=queue.max_queue,
                match_mode=queue.match_mode,
                pause_message=queue.pause_message,
                auto_pause_time=body.auto_pause_time,
                pause_check_interval_seconds=queue.pause_check_interval_seconds,
            )
        if body.pause_check_interval_seconds is not None:
            queue = QueueConfig(
                keyword=queue.keyword,
                max_queue=queue.max_queue,
                match_mode=queue.match_mode,
                pause_message=queue.pause_message,
                auto_pause_time=queue.auto_pause_time,
                pause_check_interval_seconds=int(body.pause_check_interval_seconds),
            )

        if body.overlay_title is not None:
            ui = UiConfig(
                overlay_title=body.overlay_title,
                current_title=ui.current_title,
                queue_title=ui.queue_title,
                empty_text=ui.empty_text,
                marked_color=ui.marked_color,
                overlay_show_mark=ui.overlay_show_mark,
            )
        if body.current_title is not None:
            ui = UiConfig(
                overlay_title=ui.overlay_title,
                current_title=body.current_title,
                queue_title=ui.queue_title,
                empty_text=ui.empty_text,
                marked_color=ui.marked_color,
                overlay_show_mark=ui.overlay_show_mark,
            )
        if body.queue_title is not None:
            ui = UiConfig(
                overlay_title=ui.overlay_title,
                current_title=ui.current_title,
                queue_title=body.queue_title,
                empty_text=ui.empty_text,
                marked_color=ui.marked_color,
                overlay_show_mark=ui.overlay_show_mark,
            )
        if body.empty_text is not None:
            ui = UiConfig(
                overlay_title=ui.overlay_title,
                current_title=ui.current_title,
                queue_title=ui.queue_title,
                empty_text=str(body.empty_text),
                marked_color=ui.marked_color,
                overlay_show_mark=ui.overlay_show_mark,
            )
        if body.marked_color is not None:
            ui = UiConfig(
                overlay_title=ui.overlay_title,
                current_title=ui.current_title,
                queue_title=ui.queue_title,
                empty_text=ui.empty_text,
                marked_color=body.marked_color,
                overlay_show_mark=ui.overlay_show_mark,
            )
        if body.overlay_show_mark is not None:
            ui = UiConfig(
                overlay_title=ui.overlay_title,
                current_title=ui.current_title,
                queue_title=ui.queue_title,
                empty_text=ui.empty_text,
                marked_color=ui.marked_color,
                overlay_show_mark=bool(body.overlay_show_mark),
            )

        if body.custom_css_path is not None:
            style = StyleConfig(custom_css_path=body.custom_css_path)

        ol = bili.open_live
        wb = bili.web
        mode = getattr(bili, "mode", "auto")
        if body.bilibili_mode is not None:
            mode_raw = str(body.bilibili_mode).strip().lower()
            if mode_raw not in ("auto", "open_live", "web"):
                raise HTTPException(status_code=400, detail="bilibili_mode must be one of auto|open_live|web")
            mode = mode_raw
        if body.open_live_access_key is not None:
            ol = OpenLiveConfig(
                access_key=body.open_live_access_key,
                access_secret=ol.access_secret,
                app_id=ol.app_id,
                identity_code=ol.identity_code,
            )
        if body.open_live_access_secret is not None:
            ol = OpenLiveConfig(
                access_key=ol.access_key,
                access_secret=body.open_live_access_secret,
                app_id=ol.app_id,
                identity_code=ol.identity_code,
            )
        if body.open_live_app_id is not None:
            ol = OpenLiveConfig(
                access_key=ol.access_key,
                access_secret=ol.access_secret,
                app_id=int(body.open_live_app_id),
                identity_code=ol.identity_code,
            )
        if body.open_live_identity_code is not None:
            ol = OpenLiveConfig(
                access_key=ol.access_key,
                access_secret=ol.access_secret,
                app_id=ol.app_id,
                identity_code=body.open_live_identity_code,
            )

        if body.web_sessdata is not None:
            wb = WebDanmakuConfig(
                sessdata=body.web_sessdata,
                room_id=wb.room_id,
                auto_fetch_cookie=wb.auto_fetch_cookie,
            )
        if body.web_room_id is not None:
            wb = WebDanmakuConfig(
                sessdata=wb.sessdata,
                room_id=int(body.web_room_id),
                auto_fetch_cookie=wb.auto_fetch_cookie,
            )
        if body.web_auto_fetch_cookie is not None:
            wb = WebDanmakuConfig(
                sessdata=wb.sessdata,
                room_id=wb.room_id,
                auto_fetch_cookie=bool(body.web_auto_fetch_cookie),
            )

        bili = BiliConfig(mode=mode, open_live=ol, web=wb)

        # Always restart into stopped state.
        runtime = RuntimeConfig(
            test_enabled=bool(ctx.runtime.test_enabled),
            autostart=False,
        )

        new_cfg = AppConfig(server=server, queue=queue, ui=ui, style=style, runtime=runtime, bilibili=bili)
        save_config(new_cfg, ctx.config_path)

        if app.state.restart_event is not None:
            app.state.restart_event.set()

        return {
            "ok": True,
            "restarting": True,
            "admin_url": f"http://{server.host}:{server.port}/admin",
            "overlay_url": f"http://{server.host}:{server.port}/overlay",
        }

    @app.post("/api/bilibili/fetch_sessdata")
    async def api_bilibili_fetch_sessdata() -> dict[str, Any]:
        sess, err = ctx.fetch_browser_sessdata()
        if err:
            raise HTTPException(status_code=400, detail=err)
        return {"sessdata": sess or ""}

    @app.post("/api/queue/remove")
    async def api_queue_remove(body: QueueRemoveIn) -> dict[str, Any]:
        if ctx.runtime.status != "running":
            raise HTTPException(status_code=400, detail="runtime is not running")
        ok = ctx.queue.remove(body.user_key)
        if not ok:
            raise HTTPException(status_code=404, detail="not found")
        await ctx.broadcast_state()
        return ctx.state_payload()

    @app.post("/api/queue/pause")
    async def api_queue_pause(body: QueuePauseIn) -> dict[str, Any]:
        ok, err = await ctx.set_queue_paused(body.paused, reason=body.reason)
        if not ok:
            raise HTTPException(status_code=400, detail=err or "failed")
        return ctx.state_payload()

    @app.post("/api/queue/auto_pause_minutes")
    async def api_queue_auto_pause_minutes(body: QueueAutoPauseIn) -> dict[str, Any]:
        ok, err = await ctx.set_auto_pause_time(body.time_str)
        if not ok:
            raise HTTPException(status_code=400, detail=err or "failed")
        return ctx.state_payload()

    @app.post("/api/queue/pin_top")
    async def api_queue_pin_top(body: QueuePinTopIn) -> dict[str, Any]:
        if ctx.runtime.status != "running":
            raise HTTPException(status_code=400, detail="runtime is not running")
        ok = ctx.queue.pin_top(body.user_key)
        if not ok:
            raise HTTPException(status_code=404, detail="not found")
        await ctx.broadcast_state()
        return ctx.state_payload()

    @app.post("/api/queue/toggle_mark")
    async def api_queue_toggle_mark(body: QueueToggleMarkIn) -> dict[str, Any]:
        if ctx.runtime.status != "running":
            raise HTTPException(status_code=400, detail="runtime is not running")
        ok = ctx.queue.set_marked(body.user_key, body.marked)
        if not ok:
            raise HTTPException(status_code=404, detail="not found")
        await ctx.broadcast_state()
        return ctx.state_payload()

    @app.post("/api/test/danmaku")
    async def api_test_danmaku(body: TestDanmakuIn) -> dict[str, Any]:
        if ctx.runtime.status != "running":
            raise HTTPException(status_code=400, detail="runtime is not running")
        if not ctx.runtime.test_enabled:
            raise HTTPException(status_code=400, detail="test is not enabled")
        ev = DanmakuEvent(uname=body.uname, msg=body.msg, user_key=body.uname, source="test")
        changed, reason = await ctx.process_event(ev)
        if changed:
            await ctx.broadcast_state()
        return {"ok": True, "changed": changed, "reason": reason}

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        await ctx.ws.add(ws)
        await ws.send_text(json.dumps(ctx.state_payload(), ensure_ascii=False))
        try:
            while True:
                # Keepalive / ignore client messages.
                _ = await ws.receive_text()
        except asyncio.CancelledError:
            # Server is restarting/shutting down.
            await ctx.ws.remove(ws)
            return
        except WebSocketDisconnect:
            await ctx.ws.remove(ws)
        except Exception:
            await ctx.ws.remove(ws)

    @app.get("/", response_class=HTMLResponse)
    async def root(request: Request) -> Any:
        # Convenience
        return _page("admin.html")

    return app


