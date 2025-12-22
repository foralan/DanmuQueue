from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse

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
    QueuePinTopIn,
    QueueRemoveIn,
    QueueToggleMarkIn,
    RuntimeTestEnableIn,
    TestDanmakuIn,
)


def build_app(project_root: Path, *, restart_event: asyncio.Event | None = None) -> FastAPI:
    ensure_first_run_files(project_root)
    app = FastAPI()
    ctx = AppContext(project_root)
    app.state.ctx = ctx
    app.state.restart_event = restart_event

    static_dir = project_root / "static"

    @app.on_event("startup")
    async def _startup() -> None:
        await ctx.start_background_tasks()
        # Auto-start after a process restart if requested.
        if getattr(ctx.cfg, "runtime", None) and bool(ctx.cfg.runtime.autostart):
            await ctx.start_runtime()

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

    @app.get("/static/default.css", response_class=PlainTextResponse)
    async def default_css() -> str:
        return DEFAULT_CSS

    @app.get("/static/custom.css", response_class=PlainTextResponse)
    async def custom_css() -> str:
        css_path = Path(ctx.cfg.style.custom_css_path).expanduser()
        if not css_path.is_absolute():
            css_path = project_root / css_path
        if not css_path.exists():
            return ""
        return css_path.read_text(encoding="utf-8")

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
            queue = QueueConfig(keyword=body.keyword, max_queue=queue.max_queue)
        if body.max_queue is not None:
            queue = QueueConfig(keyword=queue.keyword, max_queue=int(body.max_queue))

        if body.overlay_title is not None:
            ui = UiConfig(
                overlay_title=body.overlay_title,
                marked_color=ui.marked_color,
                overlay_show_mark=ui.overlay_show_mark,
            )
        if body.marked_color is not None:
            ui = UiConfig(
                overlay_title=ui.overlay_title,
                marked_color=body.marked_color,
                overlay_show_mark=ui.overlay_show_mark,
            )
        if body.overlay_show_mark is not None:
            ui = UiConfig(
                overlay_title=ui.overlay_title,
                marked_color=ui.marked_color,
                overlay_show_mark=bool(body.overlay_show_mark),
            )

        if body.custom_css_path is not None:
            style = StyleConfig(custom_css_path=body.custom_css_path)

        ol = bili.open_live
        wb = bili.web
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
            wb = WebDanmakuConfig(sessdata=body.web_sessdata, room_id=wb.room_id)
        if body.web_room_id is not None:
            wb = WebDanmakuConfig(sessdata=wb.sessdata, room_id=int(body.web_room_id))

        bili = BiliConfig(open_live=ol, web=wb)

        # Preserve running status across restart.
        runtime = RuntimeConfig(
            test_enabled=bool(ctx.runtime.test_enabled),
            autostart=(ctx.runtime.status == "running"),
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

    @app.post("/api/queue/remove")
    async def api_queue_remove(body: QueueRemoveIn) -> dict[str, Any]:
        if ctx.runtime.status != "running":
            raise HTTPException(status_code=400, detail="runtime is not running")
        ok = ctx.queue.remove(body.user_key)
        if not ok:
            raise HTTPException(status_code=404, detail="not found")
        await ctx.broadcast_state()
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


