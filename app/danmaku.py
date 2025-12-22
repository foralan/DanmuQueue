from __future__ import annotations

import asyncio
import http.cookies
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

import aiohttp
import blivedm
import blivedm.models.open_live as open_models
import blivedm.models.web as web_models

from .config import AppConfig, DanmakuMode
from .events import DanmakuEvent


PushEvent = Callable[[DanmakuEvent], Awaitable[None]]


class _Handler(blivedm.BaseHandler):
    def __init__(self, push_event: PushEvent):
        self._push_event = push_event

    def _on_danmaku(self, client: blivedm.BLiveClient, message: web_models.DanmakuMessage):
        # schedule quickly; don't block network loop
        asyncio.create_task(
            self._push_event(
                DanmakuEvent(
                    uname=message.uname,
                    msg=message.msg,
                    user_key=str(message.uid) if message.uid else message.uname,
                    source="web",
                )
            )
        )

    def _on_open_live_danmaku(self, client: blivedm.OpenLiveClient, message: open_models.DanmakuMessage):
        asyncio.create_task(
            self._push_event(
                DanmakuEvent(
                    uname=message.uname,
                    msg=message.msg,
                    user_key=message.open_id or message.uname,
                    source="open_live",
                )
            )
        )


@dataclass
class DanmakuRuntime:
    mode: DanmakuMode
    client: object
    session: aiohttp.ClientSession
    own_session: bool


def _make_session_with_sessdata(sessdata: str) -> aiohttp.ClientSession:
    cookies = http.cookies.SimpleCookie()
    cookies["SESSDATA"] = sessdata
    cookies["SESSDATA"]["domain"] = "bilibili.com"
    session = aiohttp.ClientSession()
    session.cookie_jar.update_cookies(cookies)
    return session


def build_client(cfg: AppConfig, mode: DanmakuMode, push_event: PushEvent) -> DanmakuRuntime:
    handler = _Handler(push_event)

    if mode == "open_live":
        ol = cfg.bilibili.open_live
        session = aiohttp.ClientSession()
        client = blivedm.OpenLiveClient(
            ol.access_key,
            ol.access_secret,
            int(ol.app_id),
            ol.identity_code,
            session=session,
        )
        client.set_handler(handler)
        return DanmakuRuntime(mode=mode, client=client, session=session, own_session=True)

    # web
    web = cfg.bilibili.web
    session = _make_session_with_sessdata(web.sessdata)
    client = blivedm.BLiveClient(int(web.room_id), session=session)
    client.set_handler(handler)
    return DanmakuRuntime(mode=mode, client=client, session=session, own_session=True)


async def run_client_until_cancelled(rt: DanmakuRuntime) -> None:
    """
    Start client and keep it running until task is cancelled.
    """
    rt.client.start()
    try:
        await rt.client.join()
    except asyncio.CancelledError:
        # stop-and-close
        await rt.client.stop_and_close()
        raise
    finally:
        try:
            await rt.client.stop_and_close()
        except Exception:
            pass
        if rt.own_session:
            try:
                await rt.session.close()
            except Exception:
                pass


