"""Scraping des vidéos d'un compte YouTube ou TikTok, via yt-dlp.

yt-dlp sait lister l'ensemble des vidéos d'une chaîne YouTube ou d'un profil
TikTok, et renvoie pour chacune son nombre de vues. On utilise l'extraction
« à plat » (extract_flat) : un seul appel réseau par compte, yt-dlp paginant
en interne.

Instagram n'utilise PAS ce module : yt-dlp ne peut pas lister les posts d'un
profil Instagram de façon anonyme (erreur "login required" systématique).
Voir connectors/instagram_playwright.py, qui scrape la page publique via un
navigateur headless (comme un visiteur normal, sans compte).

Le réglage `COOKIES_FILE` (fichier de cookies au format Netscape) reste
disponible pour fiabiliser YouTube/TikTok si besoin, mais n'est pas requis.
"""

import os
from datetime import datetime

from app.config import get_settings
from app.modules.clippers.connectors.base import VideoInfo
from app.modules.clippers.connectors.errors import (
    ConnectorError,
    NotFoundError,
    RateLimitedError,
)


def _entry_to_video_info(entry: dict) -> VideoInfo | None:
    video_id = entry.get("id")
    if not video_id:
        return None

    published_at = None
    upload_date = entry.get("upload_date")
    if upload_date:
        try:
            published_at = datetime.strptime(str(upload_date), "%Y%m%d").date()
        except ValueError:
            published_at = None

    view_count = entry.get("view_count")
    duration = entry.get("duration")
    return VideoInfo(
        platform_video_id=str(video_id),
        url=entry.get("url") or entry.get("webpage_url"),
        title=entry.get("title"),
        view_count=int(view_count) if view_count is not None else None,
        duration_seconds=int(duration) if duration else None,
        published_at=published_at,
    )


def _build_ydl_options() -> dict:
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "ignoreerrors": True,
        "socket_timeout": 30,
    }
    cookies_file = get_settings().cookies_file
    if cookies_file and os.path.isfile(cookies_file):
        options["cookiefile"] = cookies_file
    return options


def fetch_account_videos(profile_url: str) -> list[VideoInfo]:
    """Renvoie la liste des vidéos publiques du compte.

    Lève une sous-classe de ConnectorError en cas d'échec réseau/blocage.
    """
    try:
        import yt_dlp
    except ImportError as exc:  # pragma: no cover
        raise ConnectorError("yt-dlp n'est pas installé") from exc

    try:
        with yt_dlp.YoutubeDL(_build_ydl_options()) as ydl:
            info = ydl.extract_info(profile_url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        message = str(exc)
        lowered = message.lower()
        if "429" in message or "rate" in lowered or "login" in lowered:
            raise RateLimitedError(message) from exc
        if "404" in message or "not found" in lowered or "unavailable" in lowered:
            raise NotFoundError(message) from exc
        raise ConnectorError(message) from exc
    except Exception as exc:  # noqa: BLE001 — yt-dlp lève des erreurs variées
        raise ConnectorError(str(exc)) from exc

    if info is None:
        raise ConnectorError("yt-dlp n'a rien renvoyé pour ce profil")

    # Un profil est une « playlist » d'entrées ; certaines chaînes exposent des
    # sous-playlists (onglets) → on aplatit récursivement les entrées.
    videos: list[VideoInfo] = []
    seen: set[str] = set()
    for entry in _iter_entries(info):
        video = _entry_to_video_info(entry)
        if video and video.platform_video_id not in seen:
            seen.add(video.platform_video_id)
            videos.append(video)
    return videos


def _iter_entries(info: dict):
    entries = info.get("entries")
    if not entries:
        # Cas où l'URL pointe une seule vidéo plutôt qu'un profil
        if info.get("id"):
            yield info
        return
    for entry in entries:
        if not entry:
            continue
        if entry.get("entries"):
            yield from _iter_entries(entry)
        else:
            yield entry
