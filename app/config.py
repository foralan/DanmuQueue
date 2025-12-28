from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

CONFIG_PATH = "config.yaml"
CUSTOM_CSS_PATH = "custom.css"

QueueMatchMode = Literal["exact", "contains"]
DanmakuModePref = Literal["auto", "open_live", "web"]

@dataclass(frozen=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 10000


@dataclass(frozen=True)
class QueueConfig:
    keyword: str = "排队"
    max_queue: int = 10  # total: current + waiting
    match_mode: QueueMatchMode = "exact"
    pause_message: str = "当前暂停排队"
    auto_pause_time: str = ""  # "HH:MM" local time, empty = disabled
    pause_check_interval_seconds: int = 60  # scheduler tick


@dataclass(frozen=True)
class UiConfig:
    overlay_title: str = "排队"
    current_title: str = "当前"
    queue_title: str = "队列"
    empty_text: str = "当前无人排队"
    marked_color: str = "#ff5a5a"
    overlay_show_mark: bool = False


@dataclass(frozen=True)
class StyleConfig:
    custom_css_path: str = f"./{CUSTOM_CSS_PATH}"


@dataclass(frozen=True)
class RuntimeConfig:
    test_enabled: bool = False
    autostart: bool = False


@dataclass(frozen=True)
class OpenLiveConfig:
    # B站开放平台（Open Live）
    access_key: str = ""
    access_secret: str = ""
    app_id: int = 0
    identity_code: str = ""  # 身份码


@dataclass(frozen=True)
class WebDanmakuConfig:
    # Web端（需要SESSDATA）
    sessdata: str = ""
    room_id: int = 0
    auto_fetch_cookie: bool = False


@dataclass(frozen=True)
class BiliConfig:
    mode: DanmakuModePref = "auto"
    open_live: OpenLiveConfig = OpenLiveConfig()
    web: WebDanmakuConfig = WebDanmakuConfig()


@dataclass(frozen=True)
class AppConfig:
    server: ServerConfig = ServerConfig()
    queue: QueueConfig = QueueConfig()
    ui: UiConfig = UiConfig()
    style: StyleConfig = StyleConfig()
    runtime: RuntimeConfig = RuntimeConfig()
    bilibili: BiliConfig = BiliConfig()


DEFAULT_CONFIG = AppConfig()

DanmakuMode = Literal["open_live", "web"]


def load_config(path: Path) -> AppConfig:
    data = {}
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return _parse_config_dict(data)


def save_config(cfg: AppConfig, path: Path) -> None:
    path.write_text(
        yaml.safe_dump(_to_dict(cfg), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def select_danmaku_mode(cfg: AppConfig) -> tuple[DanmakuMode | None, str | None]:
    """
    Return (mode, error_message). If mode is None, error_message is non-empty.
    Priority (auto): web(SESSDATA) > open_live > error.
    """
    prefer = getattr(cfg.bilibili, "mode", "auto")

    def _web_checks() -> tuple[DanmakuMode | None, str | None]:
        web = cfg.bilibili.web
        if not web.sessdata.strip():
            return None, "bilibili.web.sessdata is required when using web mode"
        if web.room_id <= 0:
            return None, "bilibili.web.room_id is required when using SESSDATA(web mode)"
        return "web", None

    ol = cfg.bilibili.open_live
    if prefer == "open_live":
        if _open_live_is_complete(ol):
            return "open_live", None
        return None, "bilibili.mode=open_live 但开放平台配置不完整"

    if prefer == "web":
        return _web_checks()

    # auto: prefer web first, then open_live
    web = cfg.bilibili.web
    if web.sessdata.strip():
        return _web_checks()
    if _open_live_is_complete(ol):
        return "open_live", None

    return None, "Missing danmaku config: provide bilibili.open_live.* or bilibili.web.sessdata"


def _open_live_is_complete(ol: OpenLiveConfig) -> bool:
    return (
        bool(ol.access_key.strip())
        and bool(ol.access_secret.strip())
        and int(ol.app_id) > 0
        and bool(ol.identity_code.strip())
    )


def _parse_config_dict(d: dict[str, Any]) -> AppConfig:
    server = d.get("server") or {}
    queue = d.get("queue") or {}
    ui = d.get("ui") or {}
    style = d.get("style") or {}
    runtime = d.get("runtime") or {}
    bilibili = d.get("bilibili") or {}

    open_live = bilibili.get("open_live") or {}
    web = bilibili.get("web") or {}
    mode_raw = str(bilibili.get("mode", "auto")).strip().lower()
    mode: DanmakuModePref = "auto" if mode_raw not in ("auto", "open_live", "web") else mode_raw  # type: ignore[assignment]

    mm_raw = str(queue.get("match_mode", DEFAULT_CONFIG.queue.match_mode)).strip().lower()
    match_mode: QueueMatchMode = "exact" if mm_raw not in ("exact", "contains") else mm_raw  # type: ignore[assignment]

    return AppConfig(
        server=ServerConfig(
            host=str(server.get("host", DEFAULT_CONFIG.server.host)),
            port=int(server.get("port", DEFAULT_CONFIG.server.port)),
        ),
        queue=QueueConfig(
            keyword=str(queue.get("keyword", DEFAULT_CONFIG.queue.keyword)),
            max_queue=int(queue.get("max_queue", DEFAULT_CONFIG.queue.max_queue)),
            match_mode=match_mode,
            pause_message=str(queue.get("pause_message", DEFAULT_CONFIG.queue.pause_message)),
            auto_pause_time=str(queue.get("auto_pause_time", DEFAULT_CONFIG.queue.auto_pause_time)),
            pause_check_interval_seconds=int(
                queue.get("pause_check_interval_seconds", DEFAULT_CONFIG.queue.pause_check_interval_seconds)
            ),
        ),
        ui=UiConfig(
            overlay_title=str(ui.get("overlay_title", DEFAULT_CONFIG.ui.overlay_title)),
            current_title=str(ui.get("current_title", DEFAULT_CONFIG.ui.current_title)),
            queue_title=str(ui.get("queue_title", DEFAULT_CONFIG.ui.queue_title)),
            empty_text=str(ui.get("empty_text", DEFAULT_CONFIG.ui.empty_text)),
            marked_color=str(ui.get("marked_color", DEFAULT_CONFIG.ui.marked_color)),
            overlay_show_mark=bool(ui.get("overlay_show_mark", DEFAULT_CONFIG.ui.overlay_show_mark)),
        ),
        style=StyleConfig(
            custom_css_path=str(style.get("custom_css_path", DEFAULT_CONFIG.style.custom_css_path)),
        ),
        runtime=RuntimeConfig(
            test_enabled=bool(runtime.get("test_enabled", DEFAULT_CONFIG.runtime.test_enabled)),
            autostart=bool(runtime.get("autostart", DEFAULT_CONFIG.runtime.autostart)),
        ),
        bilibili=BiliConfig(
            mode=mode,
            open_live=OpenLiveConfig(
                access_key=str(open_live.get("access_key", "")),
                access_secret=str(open_live.get("access_secret", "")),
                app_id=int(open_live.get("app_id", 0) or 0),
                identity_code=str(open_live.get("identity_code", "")),
            ),
            web=WebDanmakuConfig(
                sessdata=str(web.get("sessdata", "")),
                room_id=int(web.get("room_id", 0) or 0),
                auto_fetch_cookie=bool(web.get("auto_fetch_cookie", False)),
            ),
        ),
    )


def _to_dict(cfg: AppConfig) -> dict[str, Any]:
    return {
        "server": {"host": cfg.server.host, "port": cfg.server.port},
        "queue": {
            "keyword": cfg.queue.keyword,
            "max_queue": cfg.queue.max_queue,
            "match_mode": cfg.queue.match_mode,
            "pause_message": cfg.queue.pause_message,
            "auto_pause_time": cfg.queue.auto_pause_time,
            "pause_check_interval_seconds": cfg.queue.pause_check_interval_seconds,
        },
        "ui": {
            "overlay_title": cfg.ui.overlay_title,
            "current_title": cfg.ui.current_title,
            "queue_title": cfg.ui.queue_title,
            "empty_text": cfg.ui.empty_text,
            "marked_color": cfg.ui.marked_color,
            "overlay_show_mark": cfg.ui.overlay_show_mark,
        },
        "style": {"custom_css_path": cfg.style.custom_css_path},
        "bilibili": {
            "mode": cfg.bilibili.mode,
            "open_live": {
                "access_key": cfg.bilibili.open_live.access_key,
                "access_secret": cfg.bilibili.open_live.access_secret,
                "app_id": cfg.bilibili.open_live.app_id,
                "identity_code": cfg.bilibili.open_live.identity_code,
            },
            "web": {
                "sessdata": cfg.bilibili.web.sessdata,
                "room_id": cfg.bilibili.web.room_id,
                "auto_fetch_cookie": cfg.bilibili.web.auto_fetch_cookie,
            },
        },
        "runtime": {"test_enabled": cfg.runtime.test_enabled, "autostart": cfg.runtime.autostart},
    }


