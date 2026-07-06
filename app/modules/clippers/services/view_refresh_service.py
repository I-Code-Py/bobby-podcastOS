from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.settings_service import get_min_views_per_video
from app.modules.clippers.connectors.account_videos import (
    AuthRequiredError,
    ScrapingError,
    VideoInfo,
    fetch_account_videos,
)
from app.modules.clippers.models import (
    Account,
    AccountStatus,
    AccountVideo,
    AccountVideoSnapshot,
    AccountViewSnapshot,
)

log = logging.getLogger(__name__)

MAX_CONSECUTIVE_FAILURES = 3


def refresh_all(db: Session) -> dict[str, int]:
    """Refresh views for every active account. Returns stats dict."""
    accounts = (
        db.query(Account)
        .filter(Account.status.in_([AccountStatus.active, AccountStatus.error]))
        .all()
    )
    stats = {"ok": 0, "skipped": 0, "failed": 0, "auth_required": 0}
    for account in accounts:
        try:
            refresh_account(db, account)
            stats["ok"] += 1
        except AuthRequiredError:
            account.status = AccountStatus.manual_required
            db.commit()
            stats["auth_required"] += 1
        except ScrapingError as exc:
            log.warning("Scraping failed for account %s: %s", account.id, exc)
            account.consecutive_failures += 1
            if account.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                account.status = AccountStatus.error
            db.commit()
            stats["failed"] += 1
        except Exception as exc:
            log.error("Unexpected error for account %s: %s", account.id, exc, exc_info=True)
            stats["failed"] += 1
    return stats


def refresh_account(db: Session, account: Account) -> None:
    today = date.today()
    min_views = get_min_views_per_video(db)

    videos = fetch_account_videos(account.profile_url)

    filtered_total, video_count = _upsert_videos(db, account, videos, today, min_views)

    # Upsert daily account-level snapshot
    _upsert_account_snapshot(db, account.id, filtered_total, video_count, today)

    account.last_fetch_at = datetime.now(timezone.utc).replace(tzinfo=None)
    account.consecutive_failures = 0
    if account.status == AccountStatus.error:
        account.status = AccountStatus.active
    db.commit()


def _upsert_videos(
    db: Session,
    account: Account,
    videos: list[VideoInfo],
    captured_at: date,
    min_views: int,
) -> tuple[int, int]:
    # Build lookup of existing videos by platform_video_id
    existing: dict[str, AccountVideo] = {
        v.platform_video_id: v for v in account.videos
    }

    filtered_total = 0
    video_count = 0

    for info in videos:
        av = existing.get(info.platform_video_id)
        if av is None:
            av = AccountVideo(
                account_id=account.id,
                platform_video_id=info.platform_video_id,
                url=info.url,
                title=info.title,
                view_count=info.view_count,
                duration_seconds=info.duration_seconds,
                published_at=info.published_at,
                last_seen_at=captured_at,
            )
            account.videos.append(av)
            db.flush()  # get av.id
        else:
            if info.view_count is not None:
                av.view_count = info.view_count
            av.last_seen_at = captured_at
            if info.title:
                av.title = info.title

        if info.view_count is not None:
            _upsert_video_snapshot(db, av, info.view_count, captured_at)
            if info.view_count >= min_views:
                filtered_total += info.view_count
                video_count += 1

    return filtered_total, video_count


def _upsert_video_snapshot(
    db: Session, av: AccountVideo, view_count: int, captured_at: date
) -> None:
    existing = (
        db.query(AccountVideoSnapshot)
        .filter_by(account_video_id=av.id, captured_at=captured_at)
        .first()
    )
    if existing:
        existing.view_count = view_count
    else:
        db.add(AccountVideoSnapshot(
            account_video_id=av.id,
            view_count=view_count,
            captured_at=captured_at,
        ))


def _upsert_account_snapshot(
    db: Session,
    account_id: int,
    total_views: int,
    video_count: int,
    captured_at: date,
) -> None:
    existing = (
        db.query(AccountViewSnapshot)
        .filter_by(account_id=account_id, captured_at=captured_at)
        .first()
    )
    if existing:
        existing.total_views = total_views
        existing.video_count = video_count
    else:
        db.add(AccountViewSnapshot(
            account_id=account_id,
            total_views=total_views,
            video_count=video_count,
            captured_at=captured_at,
        ))
