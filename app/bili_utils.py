from __future__ import annotations

import http.cookies

import aiohttp


def fetch_sessdata_from_browser() -> tuple[str | None, str | None]:
    """
    Best-effort: read SESSDATA from local browsers (Chrome/Edge/Firefox).
    Returns (sessdata, error_message). On success, error_message is None.
    """
    try:
        import browser_cookie3  # type: ignore
    except Exception as e:  # pragma: no cover - optional dependency
        return None, f"读取浏览器 Cookie 失败: {e}. 请先安装 browser-cookie3"

    for getter in (getattr(browser_cookie3, "chrome", None), getattr(browser_cookie3, "edge", None), getattr(browser_cookie3, "firefox", None)):
        if getter is None:
            continue
        try:
            jar = getter(domain_name="bilibili.com")
            for c in jar:
                if c.name == "SESSDATA" and c.value:
                    return c.value, None
        except Exception:
            # Try next browser
            continue

    return None, "未在浏览器中找到 SESSDATA（请确认已登录 B 站）"


DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0 Safari/537.36"
)


async def verify_sessdata(sessdata: str) -> tuple[bool, str]:
    """
    Verify SESSDATA by calling Bilibili nav API.
    Returns (is_valid, message)
    """
    if not sessdata or not sessdata.strip():
        return False, "SESSDATA 为空"

    cookies = http.cookies.SimpleCookie()
    cookies["SESSDATA"] = sessdata.strip()
    cookies["SESSDATA"]["domain"] = "bilibili.com"

    try:
        async with aiohttp.ClientSession() as session:
            session.cookie_jar.update_cookies(cookies)
            async with session.get(
                "https://api.bilibili.com/x/web-interface/nav",
                timeout=aiohttp.ClientTimeout(total=10),
                headers={
                    "User-Agent": DEFAULT_UA,
                    "Referer": "https://www.bilibili.com/",
                    "Origin": "https://www.bilibili.com",
                },
            ) as resp:
                if resp.status != 200:
                    return False, f"SESSDATA 验证失败，HTTP {resp.status}"
                data = await resp.json()
                if data.get("code") == 0:
                    uname = data.get("data", {}).get("uname", "未知用户")
                    return True, f"SESSDATA 有效，用户：{uname}"
                return False, f"SESSDATA 无效: {data}"
    except aiohttp.ClientError as e:
        return False, f"网络错误：{e}"
    except Exception as e:
        return False, f"验证异常：{e}"

