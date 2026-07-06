"""Séries temporelles pour suivre l'évolution des vues.

- par clippeur : total des vues (somme des comptes) jour par jour
- par compte : total du compte jour par jour
- par vidéo : vues de la vidéo jour par jour
"""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.clippers.models import (
    ACCOUNT_STATUS_ARCHIVED,
    Account,
    AccountVideo,
    AccountVideoSnapshot,
    AccountViewSnapshot,
)


def clipper_daily_totals(db: Session, clipper_id: int) -> list[tuple[date, int]]:
    rows = db.execute(
        select(
            AccountViewSnapshot.captured_at,
            func.sum(AccountViewSnapshot.total_views),
        )
        .join(Account, Account.id == AccountViewSnapshot.account_id)
        .where(Account.clipper_id == clipper_id,
               Account.status != ACCOUNT_STATUS_ARCHIVED)
        .group_by(AccountViewSnapshot.captured_at)
        .order_by(AccountViewSnapshot.captured_at)
    ).all()
    return [(d, int(total or 0)) for d, total in rows]


def account_daily_totals(db: Session, account_id: int) -> list[tuple[date, int]]:
    rows = db.execute(
        select(AccountViewSnapshot.captured_at, AccountViewSnapshot.total_views)
        .where(AccountViewSnapshot.account_id == account_id)
        .order_by(AccountViewSnapshot.captured_at)
    ).all()
    return [(d, int(v)) for d, v in rows]


def video_daily_views(db: Session, account_video_id: int) -> list[tuple[date, int]]:
    rows = db.execute(
        select(AccountVideoSnapshot.captured_at, AccountVideoSnapshot.view_count)
        .where(AccountVideoSnapshot.account_video_id == account_video_id)
        .order_by(AccountVideoSnapshot.captured_at)
    ).all()
    return [(d, int(v)) for d, v in rows]


def video_histories(db: Session, account_id: int) -> list[dict]:
    """Pour chaque vidéo du compte : sa série de vues et sa croissance récente."""
    videos = db.scalars(
        select(AccountVideo).where(AccountVideo.account_id == account_id)
    ).all()
    result = []
    for video in videos:
        series = video_daily_views(db, video.id)
        values = [v for _, v in series]
        current = values[-1] if values else (video.view_count or 0)
        growth = (values[-1] - values[0]) if len(values) >= 2 else 0
        result.append({
            "video": video,
            "series": series,
            "points": values,   # clé "points" (et non "values" qui masque dict.values en Jinja)
            "current": current,
            "growth": growth,
        })
    result.sort(key=lambda r: r["current"], reverse=True)
    return result
