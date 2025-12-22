from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

CONFIG_PATH = "config.yaml"
CUSTOM_CSS_PATH = "custom.css"


@dataclass(frozen=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 10000


@dataclass(frozen=True)
class QueueConfig:
    keyword: str = "排队"
    max_queue: int = 10  # total: current + waiting


@dataclass(frozen=True)
class UiConfig:
    overlay_title: str = "排队"
    current_title: str = "当前"
    queue_title: str = "队列"
    marked_color: str = "#ff5a5a"
    overlay_show_mark: bool = True


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


@dataclass(frozen=True)
class BiliConfig:
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
    Priority: open_live > web(SESSDATA) > error.
    """
    ol = cfg.bilibili.open_live
    if _open_live_is_complete(ol):
        return "open_live", None

    web = cfg.bilibili.web
    if web.sessdata.strip():
        if web.room_id <= 0:
            return None, "bilibili.web.room_id is required when using SESSDATA(web mode)"
        return "web", None

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

    return AppConfig(
        server=ServerConfig(
            host=str(server.get("host", DEFAULT_CONFIG.server.host)),
            port=int(server.get("port", DEFAULT_CONFIG.server.port)),
        ),
        queue=QueueConfig(
            keyword=str(queue.get("keyword", DEFAULT_CONFIG.queue.keyword)),
            max_queue=int(queue.get("max_queue", DEFAULT_CONFIG.queue.max_queue)),
        ),
        ui=UiConfig(
            overlay_title=str(ui.get("overlay_title", DEFAULT_CONFIG.ui.overlay_title)),
            current_title=str(ui.get("current_title", DEFAULT_CONFIG.ui.current_title)),
            queue_title=str(ui.get("queue_title", DEFAULT_CONFIG.ui.queue_title)),
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
            open_live=OpenLiveConfig(
                access_key=str(open_live.get("access_key", "")),
                access_secret=str(open_live.get("access_secret", "")),
                app_id=int(open_live.get("app_id", 0) or 0),
                identity_code=str(open_live.get("identity_code", "")),
            ),
            web=WebDanmakuConfig(
                sessdata=str(web.get("sessdata", "")),
                room_id=int(web.get("room_id", 0) or 0),
            ),
        ),
    )


def _to_dict(cfg: AppConfig) -> dict[str, Any]:
    return {
        "server": {"host": cfg.server.host, "port": cfg.server.port},
        "queue": {"keyword": cfg.queue.keyword, "max_queue": cfg.queue.max_queue},
        "ui": {
            "overlay_title": cfg.ui.overlay_title,
            "current_title": cfg.ui.current_title,
            "queue_title": cfg.ui.queue_title,
            "marked_color": cfg.ui.marked_color,
            "overlay_show_mark": cfg.ui.overlay_show_mark,
        },
        "style": {"custom_css_path": cfg.style.custom_css_path},
        "runtime": {"test_enabled": cfg.runtime.test_enabled, "autostart": cfg.runtime.autostart},
        "bilibili": {
            "open_live": {
                "access_key": cfg.bilibili.open_live.access_key,
                "access_secret": cfg.bilibili.open_live.access_secret,
                "app_id": cfg.bilibili.open_live.app_id,
                "identity_code": cfg.bilibili.open_live.identity_code,
            },
            "web": {
                "sessdata": cfg.bilibili.web.sessdata,
                "room_id": cfg.bilibili.web.room_id,
            },
        },
    }


