import logging
import time
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import get_settings
from app.core.settings_service import get_min_views_per_video
from app.modules.clippers.connectors.account_videos import fetch_account_videos
from app.modules.clippers.connectors.base import VideoInfo
from app.modules.clippers.connectors.errors import ConnectorError, RateLimitedError
from app.modules.clippers.connectors.instagram_playwright import (
    fetch_instagram_profile_videos,
)
from app.modules.clippers.models import (
    ACCOUNT_STATUS_ACTIVE,
    ACCOUNT_STATUS_MANUAL_REQUIRED,
    PLATFORM_INSTAGRAM,
    SNAPSHOT_SOURCE_AUTO,
    SNAPSHOT_SOURCE_MANUAL,
    Account,
    AccountVideo,
    AccountVideoSnapshot,
    AccountViewSnapshot,
)

logger = logging.getLogger(__name__)


@retry(
    retry=retry_if_exception_type((RateLimitedError, ConnectorError)),
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=2, max=30),
    reraise=True,
)
def _fetch_with_retry(profile_url: str, platform: str) -> list[VideoInfo]:
    # Instagram bloque le listing anonyme via yt-dlp (login required
    # systématique) : on passe par un navigateur headless à la place, qui
    # accède à la page publique du profil comme un visiteur normal.
    if platform == PLATFORM_INSTAGRAM:
        return fetch_instagram_profile_videos(profile_url)
    return fetch_account_videos(profile_url)


def _upsert_video_snapshot(db: Session, video: AccountVideo, view_count: int,
                           captured_at: date) -> None:
    snapshot = db.scalar(
        select(AccountVideoSnapshot).where(
            AccountVideoSnapshot.account_video_id == video.id,
            AccountVideoSnapshot.captured_at == captured_at,
        )
    ) if video.id is not None else None
    if snapshot is None:
        video.snapshots.append(
            AccountVideoSnapshot(view_count=view_count, captured_at=captured_at)
        )
    else:
        snapshot.view_count = view_count


def _upsert_videos(db: Session, account: Account, videos: list[VideoInfo],
                   captured_at: date, min_views: int) -> tuple[int, int]:
    """Met à jour/insère les vidéos scrapées, enregistre l'historique par vidéo,
    et calcule le total en ne comptant QUE les vidéos ayant au moins `min_views`
    vues. Retourne (total_comptabilisé, nb_vidéos_comptabilisées)."""
    existing = {v.platform_video_id: v for v in account.videos}
    now = datetime.now(timezone.utc)
    total = 0
    counted = 0
    for video in videos:
        row = existing.get(video.platform_video_id)
        if row is None:
            row = AccountVideo(
                account_id=account.id, platform_video_id=video.platform_video_id
            )
            # via la relation : la collection en mémoire reste cohérente
            account.videos.append(row)
            existing[video.platform_video_id] = row
        row.url = video.url or row.url
        row.title = video.title or row.title
        if video.view_count is not None:
            row.view_count = video.view_count
        if video.duration_seconds is not None:
            row.duration_seconds = video.duration_seconds
        if video.published_at is not None:
            row.published_at = video.published_at
        row.last_seen_at = now
        # Historique jour par jour + total filtré par le seuil
        if video.view_count is not None:
            _upsert_video_snapshot(db, row, video.view_count, captured_at)
            if video.view_count >= min_views:
                total += video.view_count
                counted += 1
    return total, counted


def _record_snapshot(db: Session, account: Account, total_views: int,
                     video_count: int, captured_at: date) -> None:
    snapshot = db.scalar(
        select(AccountViewSnapshot).where(
            AccountViewSnapshot.account_id == account.id,
            AccountViewSnapshot.captured_at == captured_at,
        )
    )
    if snapshot is None:
        snapshot = AccountViewSnapshot(account_id=account.id, captured_at=captured_at)
        db.add(snapshot)
    elif snapshot.source == SNAPSHOT_SOURCE_MANUAL:
        # Une saisie manuelle du jour prime sur la collecte automatique
        return
    snapshot.total_views = total_views
    snapshot.video_count = video_count
    snapshot.source = SNAPSHOT_SOURCE_AUTO


def refresh_account(db: Session, account: Account,
                    captured_at: date | None = None) -> bool:
    """Scrape toutes les vidéos du compte et enregistre le total du jour.
    Retourne True si la collecte a réussi."""
    captured_at = captured_at or date.today()
    min_views = get_min_views_per_video(db)
    try:
        videos = _fetch_with_retry(account.profile_url, account.platform)
    except Exception as exc:  # noqa: BLE001 — tout échec suit le même chemin
        _apply_failure(db, account, exc)
        return False

    total, count = _upsert_videos(db, account, videos, captured_at, min_views)
    db.flush()
    _record_snapshot(db, account, total, count, captured_at)
    account.last_fetch_at = datetime.now(timezone.utc)
    account.last_fetch_status = "ok"
    account.last_fetch_error = None
    account.consecutive_failures = 0
    if account.status == ACCOUNT_STATUS_MANUAL_REQUIRED:
        account.status = ACCOUNT_STATUS_ACTIVE
    db.commit()
    return True


def _apply_failure(db: Session, account: Account, error: Exception) -> None:
    settings = get_settings()
    account.last_fetch_at = datetime.now(timezone.utc)
    account.last_fetch_status = "error"
    account.last_fetch_error = str(error)[:2000]
    account.consecutive_failures += 1
    if account.consecutive_failures >= settings.manual_required_after_failures:
        account.status = ACCOUNT_STATUS_MANUAL_REQUIRED
        logger.warning("Compte %s (%s) passe en saisie manuelle après %d échecs",
                       account.id, account.platform, account.consecutive_failures)
    db.commit()


def refresh_all(db: Session) -> dict:
    """Rafraîchit tous les comptes actifs, avec un délai entre chaque scraping
    pour rester discret (scraping public sans compte connecté)."""
    settings = get_settings()
    accounts = list(
        db.scalars(select(Account).where(Account.status == ACCOUNT_STATUS_ACTIVE))
    )
    stats = {"ok": 0, "failed": 0, "total": len(accounts)}
    for index, account in enumerate(accounts):
        if index > 0:
            delay = (settings.instagram_delay_seconds
                     if account.platform == PLATFORM_INSTAGRAM
                     else settings.scrape_delay_seconds)
            time.sleep(delay)
        if refresh_account(db, account):
            stats["ok"] += 1
        else:
            stats["failed"] += 1
    logger.info("Refresh terminé : %(ok)d ok, %(failed)d échecs sur %(total)d", stats)
    return stats


def reactivate_account(db: Session, account: Account) -> None:
    account.status = ACCOUNT_STATUS_ACTIVE
    account.consecutive_failures = 0
    db.commit()
