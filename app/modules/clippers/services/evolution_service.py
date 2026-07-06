from __future__ import annotations

from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.modules.clippers.models import (
    Account,
    AccountVideo,
    AccountVideoSnapshot,
    AccountViewSnapshot,
    Clipper,
)


def clipper_daily_totals(
    db: Session, clipper_id: int
) -> list[tuple[date, int]]:
    """Sum of filtered views per day across all accounts of a clipper."""
    rows = (
        db.query(AccountViewSnapshot.captured_at, func.sum(AccountViewSnapshot.total_views))
        .join(Account)
        .filter(Account.clipper_id == clipper_id)
        .group_by(AccountViewSnapshot.captured_at)
        .order_by(AccountViewSnapshot.captured_at)
        .all()
    )
    return [(r[0], r[1]) for r in rows]


def account_daily_totals(
    db: Session, account_id: int
) -> list[tuple[date, int]]:
    rows = (
        db.query(AccountViewSnapshot.captured_at, AccountViewSnapshot.total_views)
        .filter_by(account_id=account_id)
        .order_by(AccountViewSnapshot.captured_at)
        .all()
    )
    return [(r[0], r[1]) for r in rows]


def video_histories(
    db: Session, account_id: int
) -> list[dict]:
    """Return per-video snapshot histories for an account."""
    videos = (
        db.query(AccountVideo)
        .filter_by(account_id=account_id)
        .order_by(AccountVideo.view_count.desc().nullslast())
        .limit(20)
        .all()
    )
    result = []
    for video in videos:
        snapshots = (
            db.query(AccountVideoSnapshot)
            .filter_by(account_video_id=video.id)
            .order_by(AccountVideoSnapshot.captured_at)
            .all()
        )
        # Use "points" key to avoid conflict with Jinja's dict.values() builtin
        result.append({
            "video": video,
            "points": [s.view_count for s in snapshots],
            "dates": [str(s.captured_at) for s in snapshots],
        })
    return result
