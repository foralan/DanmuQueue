from __future__ import annotations

from pydantic import BaseModel, Field


class RuntimeTestEnableIn(BaseModel):
    enabled: bool


class RuntimeStartIn(BaseModel):
    # reserved for future options
    pass


class QueueRemoveIn(BaseModel):
    user_key: str = Field(min_length=1, description="open_id/uid or uname")


class QueuePinTopIn(BaseModel):
    user_key: str = Field(min_length=1)


class QueueToggleMarkIn(BaseModel):
    user_key: str = Field(min_length=1)
    marked: bool


class TestDanmakuIn(BaseModel):
    uname: str = Field(min_length=1)
    msg: str = Field(min_length=1)


class ConfigUpdateIn(BaseModel):
    # server
    host: str | None = None
    port: int | None = None

    # ui
    overlay_title: str | None = None
    current_title: str | None = None
    queue_title: str | None = None
    empty_text: str | None = None
    marked_color: str | None = None
    overlay_show_mark: bool | None = None

    # queue
    keyword: str | None = None
    max_queue: int | None = None
    match_mode: str | None = None

    # style
    custom_css_path: str | None = None

    # danmaku: open live
    open_live_access_key: str | None = None
    open_live_access_secret: str | None = None
    open_live_app_id: int | None = None
    open_live_identity_code: str | None = None

    # danmaku: web
    web_sessdata: str | None = None
    web_room_id: int | None = None
    web_auto_fetch_cookie: bool | None = None

    # danmaku: mode
    bilibili_mode: str | None = None


