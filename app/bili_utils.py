from __future__ import annotations

import http.cookies

import aiohttp


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
