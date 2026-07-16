"""Séries temporelles pour suivre l'évolution des vues.

- par clippeur : total des vues (somme des comptes) jour par jour
- par compte : total du compte jour par jour
- par vidéo : vues de la vidéo jour par jour
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.clippers.models import (
    ACCOUNT_STATUS_ARCHIVED,
    Account,
    AccountVideo,
    AccountVideoSnapshot,
    AccountViewSnapshot,
)


def clipper_daily_totals(db: Session, clipper_id: int) -> list[tuple[date, int]]:
    """Total de vues du clippeur (somme de ses comptes), jour par jour.

    Un compte dont le scraping a échoué un jour donné n'a pas de snapshot ce
    jour-là. Les sommer par un simple `GROUP BY captured_at` le compterait alors
    pour zéro : la courbe plonge, puis explose le lendemain quand le compte
    réapparaît. Vu du dashboard comme du rapport Discord, ce sont des chutes et
    des pics qui n'ont jamais eu lieu.

    On reporte donc, pour chaque compte et chaque jour, son dernier relevé
    connu : les vues d'un compte ne disparaissent pas parce qu'on a échoué à les
    lire. Tant qu'un compte n'a aucun relevé (il n'était pas encore suivi), il
    ne compte pour rien — là, le zéro est la vérité.
    """
    rows = db.execute(
        select(
            AccountViewSnapshot.captured_at,
            AccountViewSnapshot.account_id,
            AccountViewSnapshot.total_views,
        )
        .join(Account, Account.id == AccountViewSnapshot.account_id)
        .where(Account.clipper_id == clipper_id,
               Account.status != ACCOUNT_STATUS_ARCHIVED)
        .order_by(AccountViewSnapshot.captured_at)
    ).all()
    if not rows:
        return []

    by_day: dict[date, dict[int, int]] = {}
    for captured_at, account_id, total_views in rows:
        by_day.setdefault(captured_at, {})[account_id] = int(total_views or 0)

    totals: list[tuple[date, int]] = []
    last_known: dict[int, int] = {}
    for day in sorted(by_day):
        last_known.update(by_day[day])
        totals.append((day, sum(last_known.values())))
    return totals


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
