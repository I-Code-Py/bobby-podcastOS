"""Connector — fetches all public videos from a social account profile.

YouTube / TikTok: yt-dlp (flat playlist extraction, no API key required).
Instagram: Playwright headless Chromium — yt-dlp always fails with
"login required" on Instagram even for public profiles, so we load the
page in a real browser, scroll to expose all posts, and read view counts
directly from the rendered DOM.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date

import yt_dlp


class ScrapingError(Exception):
    pass


class AuthRequiredError(ScrapingError):
    """Platform requires authentication (cookies) to access this account."""
    pass


@dataclass
class VideoInfo:
    platform_video_id: str
    url: str
    title: str | None = None
    view_count: int | None = None
    duration_seconds: int | None = None
    published_at: date | None = None


_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)

# Instagram Playwright tuning
_IG_MAX_SCROLLS = 15
_IG_MAX_STALE = 3
_IG_SCROLL_PAUSE_MS = 1500
_IG_COUNT_RE = re.compile(r"^([\d.,]+)\s*([KMB]?)$", re.IGNORECASE)
_IG_SHORTCODE_RE = re.compile(r"/(reel|p)/([\w-]+)")
_IG_SUFFIX = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}


def fetch_account_videos(profile_url: str) -> list[VideoInfo]:
    url_lower = profile_url.lower()
    if "tiktok.com" in url_lower:
        return _fetch_tiktok(profile_url)
    elif "instagram.com" in url_lower:
        return _fetch_instagram(profile_url)
    else:
        return _fetch_generic(profile_url)


# ---------------------------------------------------------------------------
# Generic / YouTube
# ---------------------------------------------------------------------------

def _fetch_generic(profile_url: str) -> list[VideoInfo]:
    return _run_ydl(profile_url, _base_opts())


# ---------------------------------------------------------------------------
# TikTok
# ---------------------------------------------------------------------------

def _fetch_tiktok(profile_url: str) -> list[VideoInfo]:
    opts = _base_opts()
    opts["http_headers"] = {"User-Agent": _MOBILE_UA}
    m = re.search(r"tiktok\.com/@([^/?#]+)", profile_url)
    handle = m.group(1) if m else profile_url.rstrip("/").split("/")[-1].lstrip("@")
    return _run_ydl(f"https://www.tiktok.com/@{handle}", opts)


# ---------------------------------------------------------------------------
# Instagram — Playwright headless browser
# ---------------------------------------------------------------------------

def _fetch_instagram(profile_url: str) -> list[VideoInfo]:
    m = re.search(
        r"instagram\.com/(?!reel/|reels/|p/|explore/|stories/)([^/?#]+)",
        profile_url,
    )
    handle = m.group(1) if m else profile_url.rstrip("/").split("/")[-1]
    url = f"https://www.instagram.com/{handle}/"

    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ScrapingError(
            "playwright n'est pas installé — lancez: playwright install chromium"
        ) from exc

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--disable-dev-shm-usage"],
            )
            try:
                page = browser.new_page(
                    user_agent=_DESKTOP_UA,
                    viewport={"width": 1280, "height": 1600},
                )
                resp = page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                if resp is not None and resp.status == 404:
                    raise ScrapingError(f"Profil Instagram introuvable : {url}")

                _ig_dismiss_overlays(page)
                page.wait_for_timeout(1500)

                posts: dict[str, dict] = {}
                stale = 0
                for _ in range(_IG_MAX_SCROLLS):
                    before = len(posts)
                    posts.update(_ig_extract_posts(page))
                    if len(posts) == before:
                        stale += 1
                        if stale >= _IG_MAX_STALE:
                            break
                    else:
                        stale = 0
                    page.mouse.wheel(0, 2500)
                    page.wait_for_timeout(_IG_SCROLL_PAUSE_MS)
                posts.update(_ig_extract_posts(page))
            finally:
                browser.close()
    except ScrapingError:
        raise
    except PlaywrightError as exc:
        raise ScrapingError(f"Navigateur headless : {exc}") from exc
    except Exception as exc:
        raise ScrapingError(str(exc)) from exc

    if not posts:
        raise ScrapingError(
            "Aucun post trouvé — profil privé, structure Instagram changée, ou blocage temporaire"
        )

    return [
        VideoInfo(
            platform_video_id=shortcode,
            url=data["url"],
            view_count=data["view_count"],
        )
        for shortcode, data in posts.items()
    ]


def _ig_dismiss_overlays(page) -> None:
    for selector in [
        "button:has-text('Allow all cookies')",
        "button:has-text('Autoriser les cookies')",
        "button:has-text('Accept all')",
        "button:has-text('Tout accepter')",
    ]:
        try:
            page.locator(selector).first.click(timeout=2000)
        except Exception:
            pass
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass


def _ig_extract_posts(page) -> dict[str, dict]:
    posts: dict[str, dict] = {}
    anchors = page.locator("main a[href*='/reel/'], main a[href*='/p/']")
    for i in range(anchors.count()):
        anchor = anchors.nth(i)
        href = anchor.get_attribute("href") or ""
        match = _IG_SHORTCODE_RE.search(href)
        if not match:
            continue
        shortcode = match.group(2)
        if shortcode in posts:
            continue
        view_count = None
        try:
            for text in anchor.locator("span").all_inner_texts():
                parsed = _ig_parse_count(text)
                if parsed is not None:
                    view_count = parsed
                    break
        except Exception:
            pass
        posts[shortcode] = {
            "url": f"https://www.instagram.com/reel/{shortcode}/",
            "view_count": view_count,
        }
    return posts


def _ig_parse_count(text: str) -> int | None:
    text = text.strip()
    match = _IG_COUNT_RE.match(text)
    if not match:
        return None
    number_part, suffix = match.groups()
    if suffix:
        number_part = number_part.replace(",", ".")
    else:
        number_part = number_part.replace(",", "")
    try:
        value = float(number_part)
    except ValueError:
        return None
    return int(value * _IG_SUFFIX.get(suffix.upper(), 1))


# ---------------------------------------------------------------------------
# Shared yt-dlp helpers
# ---------------------------------------------------------------------------

def _base_opts() -> dict:
    return {
        "extract_flat": "in_playlist",
        "ignoreerrors": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "retries": 3,
    }


def _run_ydl(url: str, opts: dict) -> list[VideoInfo]:
    class _Logger:
        def debug(self, msg: str) -> None:
            pass
        def warning(self, msg: str) -> None:
            pass
        def error(self, msg: str) -> None:
            pass

    opts = {**opts, "logger": _Logger()}

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.ExtractorError as exc:
        raise ScrapingError(str(exc)) from exc
    except Exception as exc:
        raise ScrapingError(str(exc)) from exc

    if info is None:
        return []

    entries: list[dict] = []
    _collect_entries(info, entries)
    return [v for v in (_entry_to_video(e) for e in entries) if v is not None]


def _collect_entries(info: dict, out: list[dict]) -> None:
    if info.get("_type") in ("playlist", "multi_video"):
        for entry in info.get("entries") or []:
            if entry:
                _collect_entries(entry, out)
    elif info.get("id"):
        out.append(info)


def _entry_to_video(entry: dict) -> VideoInfo | None:
    vid_id = entry.get("id")
    if not vid_id:
        return None
    url = entry.get("url") or entry.get("webpage_url") or ""
    if not url:
        return None

    view_count = entry.get("view_count")
    if view_count is not None:
        try:
            view_count = int(view_count)
        except (TypeError, ValueError):
            view_count = None

    duration = entry.get("duration")
    if duration is not None:
        try:
            duration = int(duration)
        except (TypeError, ValueError):
            duration = None

    published_at: date | None = None
    upload_date = entry.get("upload_date")
    if upload_date and len(upload_date) == 8:
        try:
            published_at = date(
                int(upload_date[:4]), int(upload_date[4:6]), int(upload_date[6:8])
            )
        except ValueError:
            pass

    return VideoInfo(
        platform_video_id=str(vid_id),
        url=url,
        title=entry.get("title"),
        view_count=view_count,
        duration_seconds=duration,
        published_at=published_at,
    )
