"""Scraping de toutes les vidéos publiques d'un compte, via yt-dlp.

yt-dlp sait lister l'ensemble des vidéos d'une chaîne YouTube, d'un profil
TikTok ou d'un profil Instagram sans authentification, et renvoie pour chacune
son nombre de vues. On utilise l'extraction « à plat » (extract_flat) : un seul
appel réseau par compte, yt-dlp paginant en interne.

Limites connues :
  - Instagram est le plus fragile (yt-dlp peut réclamer des cookies pour
    lister un profil) → repli en saisie manuelle du total dans l'UI.
  - Le nombre de vues peut manquer pour certaines vidéos selon la plateforme ;
    elles comptent alors pour 0 dans le total (mais restent enregistrées).
"""

from datetime import datetime

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
    return {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "ignoreerrors": True,
        "socket_timeout": 30,
    }


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
