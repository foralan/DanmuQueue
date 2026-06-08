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
    priority_color: str | None = None
    pause_color: str | None = None
    overlay_show_mark: bool | None = None

    # queue
    keyword: str | None = None
    priority_keyword: str | None = None
    max_queue: int | None = None
    match_mode: str | None = None
    pause_message: str | None = None
    auto_pause_time: str | None = None
    pause_check_interval_seconds: int | None = None

    # style
    custom_css_path: str | None = None

    # danmaku: web
    web_sessdata: str | None = None
    web_room_id: int | None = None


class QueuePauseIn(BaseModel):
    paused: bool
    reason: str | None = None


class QueueAutoPauseIn(BaseModel):
    time_str: str  # "HH:MM"
