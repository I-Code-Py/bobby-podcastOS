"""Scraping des reels d'un profil Instagram via l'API Apify.

Voie recommandée pour Instagram : l'actor public « apify/instagram-reel-scraper »
liste les reels d'un profil public avec leur nombre de vues, en passant par les
proxies d'Apify. Donc :

- **aucun cookie / aucun compte** à fournir (pas de risque de ban d'un compte) ;
- contourne le blocage 429 d'Instagram sur les IP datacenter (c'est Apify qui
  requête, pas notre VPS) ;
- renvoie le `videoPlayCount` (nombre de lectures) de chaque reel — la métrique
  qui sert au calcul des paiements.

Piloté par le réglage `apify_token`. Coût borné par `instagram_apify_results_limit`.
En cas d'échec (quota épuisé, actor en erreur, profil injoignable), on lève une
sous-classe de ConnectorError : le compte bascule alors en repli (cookies si
configuré, sinon saisie manuelle) comme les autres connecteurs.
"""

import logging
import re
import time
from datetime import date, datetime, timedelta

import httpx

from app.config import get_settings
from app.modules.clippers.connectors.base import VideoInfo
from app.modules.clippers.connectors.errors import (
    ConnectorError,
    RateLimitedError,
)

logger = logging.getLogger(__name__)

_API_BASE = "https://api.apify.com/v2"
# Actor public « apify/instagram-reel-scraper » (slug API avec ~).
_ACTOR_ID = "apify~instagram-reel-scraper"

_POLL_INTERVAL_S = 4
_POLL_TIMEOUT_S = 180  # temps max d'attente d'un run (cold start + scraping)

# Récupère le premier segment de chemin après instagram.com : le username.
_USERNAME_RE = re.compile(r"instagram\.com/([^/?#]+)", re.IGNORECASE)
# Segments qui ne sont pas des usernames (au cas où l'URL pointe un post).
_RESERVED = {"p", "reel", "reels", "explore", "stories", "tv", "s"}


def _extract_username(profile_url: str) -> str | None:
    match = _USERNAME_RE.search(profile_url)
    if not match:
        return None
    username = match.group(1).strip().strip("@")
    if not username or username.lower() in _RESERVED:
        return None
    return username


def _item_to_video(item: dict) -> VideoInfo | None:
    """Convertit un reel renvoyé par l'actor en VideoInfo. None si inexploitable."""
    video_id = item.get("shortCode") or item.get("id")
    if not video_id:
        return None

    # videoPlayCount (lectures) est la métrique « vues » la plus large ; on
    # retombe sur videoViewCount si l'actor ne renvoie pas le playCount.
    views = item.get("videoPlayCount")
    if views is None:
        views = item.get("videoViewCount")

    published_at = None
    timestamp = item.get("timestamp")
    if timestamp:
        try:
            published_at = datetime.fromisoformat(
                str(timestamp).replace("Z", "+00:00")
            ).date()
        except ValueError:
            published_at = None

    caption = item.get("caption") or None
    if caption:
        caption = caption.strip()[:300] or None

    duration = item.get("videoDuration")

    return VideoInfo(
        platform_video_id=str(video_id),
        url=item.get("url"),
        title=caption,
        view_count=int(views) if views is not None else None,
        duration_seconds=int(duration) if duration else None,
        published_at=published_at,
    )


def _run_actor(token: str, username: str, results_limit: int,
               newer_than: str | None) -> list[dict]:
    """Démarre l'actor, attend sa fin et renvoie les items du dataset.

    `newer_than` (date ISO AAAA-MM-JJ) active le filtre natif `onlyPostsNewerThan`
    de l'actor : on ne récupère que les reels postés depuis cette date."""
    params = {"token": token}
    payload = {"username": [username], "resultsLimit": results_limit}
    if newer_than:
        payload["onlyPostsNewerThan"] = newer_than
    try:
        with httpx.Client(timeout=30.0) as client:
            start = client.post(
                f"{_API_BASE}/acts/{_ACTOR_ID}/runs", params=params, json=payload
            )
            if start.status_code in (401, 403):
                raise RateLimitedError(
                    f"Apify : accès refusé ({start.status_code}) — token invalide "
                    "ou quota épuisé."
                )
            if start.status_code == 402:
                raise RateLimitedError("Apify : quota mensuel épuisé (HTTP 402).")
            start.raise_for_status()
            data = start.json()["data"]
            run_id = data["id"]
            dataset_id = data["defaultDatasetId"]

            waited = 0
            while waited < _POLL_TIMEOUT_S:
                time.sleep(_POLL_INTERVAL_S)
                waited += _POLL_INTERVAL_S
                poll = client.get(f"{_API_BASE}/actor-runs/{run_id}", params=params)
                poll.raise_for_status()
                status = poll.json()["data"]["status"]
                if status == "SUCCEEDED":
                    break
                if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                    raise ConnectorError(f"Apify : run terminé en {status}.")
            else:
                raise RateLimitedError(
                    "Apify : run trop long (timeout d'attente dépassé)."
                )

            items = client.get(
                f"{_API_BASE}/datasets/{dataset_id}/items",
                params={**params, "clean": "true"},
            )
            items.raise_for_status()
            return items.json()
    except (RateLimitedError, ConnectorError):
        raise
    except httpx.HTTPError as exc:
        raise ConnectorError(f"Apify : erreur HTTP — {exc}") from exc


def fetch_instagram_profile_videos_apify(profile_url: str) -> list[VideoInfo]:
    settings = get_settings()
    token = settings.apify_token
    if not token:
        raise ConnectorError("APIFY_TOKEN non configuré.")

    username = _extract_username(profile_url)
    if not username:
        raise ConnectorError(
            f"Impossible d'extraire le username Instagram de : {profile_url}"
        )

    results_limit = settings.instagram_apify_results_limit
    scan_days = settings.instagram_scan_days
    newer_than = None
    if scan_days and scan_days > 0:
        newer_than = (date.today() - timedelta(days=scan_days)).isoformat()

    items = _run_actor(token, username, results_limit, newer_than)
    # Pas de troncature silencieuse : si on atteint le plafond dur, il peut
    # rester des reels dans la fenêtre non récupérés -> on alerte.
    if len(items) >= results_limit:
        logger.warning(
            "Apify @%s : plafond de %d reels atteint (fenêtre %s j) — certains "
            "reels de la période peuvent manquer, augmente instagram_apify_results_limit.",
            username, results_limit, scan_days,
        )
    videos = [v for v in (_item_to_video(it) for it in items) if v is not None]
    logger.info("Apify : %d reels récupérés pour @%s (fenêtre %s j)",
                len(videos), username, scan_days or "∞")
    return videos
