from __future__ import annotations

import asyncio
import atexit
import os
import socket
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from .bootstrap import ensure_first_run_files
from .config import CONFIG_PATH, load_config
from .server import build_app


def _open_admin_later(url: str) -> None:
    # Let the server start before opening the browser.
    time.sleep(0.6)
    try:
        webbrowser.open(url, new=2)
    except Exception:
        pass


def main() -> None:
    asyncio.run(_main_async())


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _acquire_single_instance_lock(project_root: Path) -> None:
    """
    Prevent running multiple instances (which causes 'address already in use').
    """
    pidfile = project_root / ".danmuqueue.pid"
    if pidfile.exists():
        try:
            old_pid = int(pidfile.read_text(encoding="utf-8").strip() or "0")
        except Exception:
            old_pid = 0
        if _pid_is_alive(old_pid) and old_pid != os.getpid():
            raise SystemExit(
                f"Another DanmuQueue instance is already running (pid={old_pid}). "
                f"Stop it first, or delete {pidfile} if it's stale."
            )
    pidfile.write_text(str(os.getpid()), encoding="utf-8")

    def _cleanup() -> None:
        try:
            # Only delete if it's still ours.
            if pidfile.exists() and pidfile.read_text(encoding='utf-8').strip() == str(os.getpid()):
                pidfile.unlink()
        except Exception:
            pass

    atexit.register(_cleanup)


def _wait_port_free(host: str, port: int, *, timeout_s: float = 5.0) -> None:
    """
    Best-effort: wait until we can bind (host, port). Helps during fast restart.
    """
    deadline = time.time() + timeout_s
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, port))
                return
            except OSError:
                if time.time() >= deadline:
                    return
        time.sleep(0.15)


async def _main_async() -> None:
    project_root = Path.cwd()
    ensure_first_run_files(project_root)
    _acquire_single_instance_lock(project_root)

    first_open = True
    while True:
        cfg = load_config(project_root / CONFIG_PATH)
        restart_event = asyncio.Event()
        _wait_port_free(cfg.server.host, cfg.server.port, timeout_s=4.0)
        app = build_app(project_root, restart_event=restart_event)

        admin_url = f"http://{cfg.server.host}:{cfg.server.port}/admin"
        if first_open:
            first_open = False
            threading.Thread(target=_open_admin_later, args=(admin_url,), daemon=True).start()

        uv_cfg = uvicorn.Config(
            app,
            host=cfg.server.host,
            port=cfg.server.port,
            log_level="info",
        )
        server = uvicorn.Server(uv_cfg)
        async def _serve_wrapper():
            try:
                return await server.serve()
            except SystemExit as e:
                # uvicorn calls sys.exit(1) on bind errors; keep supervisor alive.
                return e

        serve_task = asyncio.create_task(_serve_wrapper())
        restart_task = asyncio.create_task(restart_event.wait())

        done, pending = await asyncio.wait(
            {serve_task, restart_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        if serve_task in done and restart_task not in done:
            # Server exited normally (Ctrl+C etc.) OR failed to bind.
            restart_task.cancel()
            res = serve_task.result()
            if isinstance(res, SystemExit) and (res.code or 0) == 1:
                # Bind failed; tell user and keep looping so they can fix port and retry.
                print(
                    f"[DanmuQueue] Failed to bind {cfg.server.host}:{cfg.server.port}. "
                    f"Is another instance running or is the port in use?"
                )
                await asyncio.sleep(0.5)
                continue
            break

        # Restart requested: ask uvicorn to exit gracefully, then loop.
        server.should_exit = True
        # Do NOT cancel serve_task, let uvicorn shutdown gracefully.
        await serve_task
        restart_task.cancel()
        # small delay to release socket cleanly
        await asyncio.sleep(0.25)


if __name__ == "__main__":
    main()


