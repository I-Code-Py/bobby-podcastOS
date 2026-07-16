"""Vue « Clipping » du SPA : les vrais clippeurs, leurs vues et ce qu'on leur doit.

Tout est dérivé des tables existantes — aucune donnée n'est inventée. Ce que la
maquette affichait en dur (clics, taux de conversion) sort d'ici à `null`, faute
d'être mesuré : voir `clicks_tracking_enabled`.
"""

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_api_user
from app.api.schemas import (
    CampaignTotals,
    ClipperOut,
    ClippingOut,
    DailyPoint,
    SourceBreakdown,
    VideoOut,
)
from app.core.auth.models import User
from app.core.settings_service import get_rate_cents
from app.db import get_db
from app.modules.clippers.models import (
    PAYMENT_METHOD_LABELS,
    PLATFORM_LABELS,
    Account,
    Clipper,
)
from app.modules.clippers.services import (
    clipper_service,
    evolution_service,
    payout_service,
    stats_service,
)

router = APIRouter(prefix="/api/v2", tags=["clipping"])

# La maquette dessine 7 barres quotidiennes par clippeur.
DAILY_WINDOW_DAYS = 7
# Le détail d'un clippeur n'affiche qu'un top vidéos ; inutile d'en transporter 196.
TOP_VIDEOS_PER_CLIPPER = 10

# Aucun tracking de clics n'existe (ni table, ni redirecteur, ni collecte). Ce
# drapeau pilote l'affichage « N/A » côté SPA. Il passera à True le jour où le
# système de liens sera branché — le contrat d'API n'aura pas à changer.
CLICKS_TRACKING_ENABLED = False


def _initials(name: str) -> str:
    parts = [p for p in name.replace("_", " ").replace("-", " ").split() if p]
    if not parts:
        return "??"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()


def _daily_points(totals: list[tuple[date, int]], days: int) -> list[DailyPoint]:
    """Transforme une série de cumuls en vues gagnées par jour.

    On prend `days + 1` points pour pouvoir calculer le delta du premier jour
    affiché. Cas limite : le tout premier snapshot n'a pas de veille — son delta
    vaut 0 et non le cumul entier, qui écraserait toutes les autres barres.

    Un delta négatif (une plateforme qui révise ses compteurs à la baisse, une
    vidéo supprimée) est ramené à 0 : on ne dessine pas une barre négative.
    """
    window = totals[-(days + 1):]
    points: list[DailyPoint] = []
    for i, (day, total) in enumerate(window):
        previous = window[i - 1][1] if i > 0 else total
        points.append(DailyPoint(date=day, views=total, delta=max(0, total - previous)))
    return points[-days:]


def _sources(clipper: Clipper) -> list[SourceBreakdown]:
    """Répartition des vues par plateforme, comme les barres « TikTok / YouTube
    Shorts / Instagram Reels » de la maquette."""
    accounts = clipper_service.active_accounts(clipper)
    aggregated: dict[str, dict[str, int]] = {}
    for account in accounts:
        entry = aggregated.setdefault(account.platform, {"views": 0, "accounts": 0})
        entry["views"] += account.latest_total_views
        entry["accounts"] += 1

    total = sum(entry["views"] for entry in aggregated.values())
    sources = [
        SourceBreakdown(
            platform=platform,
            label=PLATFORM_LABELS.get(platform, platform),
            views=entry["views"],
            share=round(entry["views"] * 100 / total, 1) if total else 0.0,
            accounts=entry["accounts"],
            clicks=None,
        )
        for platform, entry in aggregated.items()
    ]
    sources.sort(key=lambda s: s.views, reverse=True)
    return sources


def _top_videos(clipper: Clipper) -> list[VideoOut]:
    videos = [
        VideoOut(
            id=video.id,
            title=video.title,
            url=video.url,
            views=video.view_count or 0,
            platform=account.platform,
            published_at=video.published_at,
        )
        for account in clipper_service.active_accounts(clipper)
        for video in account.videos
    ]
    videos.sort(key=lambda v: v.views, reverse=True)
    return videos[:TOP_VIDEOS_PER_CLIPPER]


def _load_clippers(db: Session) -> list[Clipper]:
    """Charge clippeurs + comptes + snapshots + vidéos en une fois.

    `clipper_service.list_clippers` ne précharge que les snapshots : passer par
    lui ferait une requête vidéos par compte au premier accès.
    """
    return list(
        db.scalars(
            select(Clipper)
            .order_by(Clipper.active.desc(), Clipper.name)
            .options(
                selectinload(Clipper.accounts).selectinload(Account.snapshots),
                selectinload(Clipper.accounts).selectinload(Account.videos),
            )
        )
    )


@router.get("/clipping", response_model=ClippingOut)
def read_clipping(db: Session = Depends(get_db), _user: User = Depends(get_api_user)):
    stats = stats_service.campaign_stats(db)

    clippers: list[ClipperOut] = []
    for clipper in _load_clippers(db):
        unpaid_views, amount_due_cents = payout_service.live_unpaid_estimate_cents(db, clipper)
        daily = _daily_points(
            evolution_service.clipper_daily_totals(db, clipper.id), DAILY_WINDOW_DAYS
        )
        accounts = clipper_service.active_accounts(clipper)
        clippers.append(
            ClipperOut(
                id=clipper.id,
                name=clipper.name,
                initials=_initials(clipper.name),
                active=clipper.active,
                total_views=clipper_service.total_views(clipper),
                unpaid_views=unpaid_views,
                amount_due_cents=amount_due_cents,
                weekly_delta_views=sum(point.delta for point in daily),
                video_count=sum(len(account.videos) for account in accounts),
                payment_method=clipper.payment_method,
                payment_label=PAYMENT_METHOD_LABELS.get(clipper.payment_method)
                if clipper.payment_method
                else None,
                payment_handle=clipper.payment_handle,
                daily=daily,
                sources=_sources(clipper),
                videos=_top_videos(clipper),
                clicks=None,
                conversion=None,
            )
        )

    # Classement par vues gagnées sur la semaine : c'est ce que la maquette met
    # en avant (« premier de la semaine »), pas le cumul historique.
    clippers.sort(key=lambda c: c.weekly_delta_views, reverse=True)

    return ClippingOut(
        rate_cents_per_1000=get_rate_cents(db),
        clicks_tracking_enabled=CLICKS_TRACKING_ENABLED,
        totals=CampaignTotals(
            total_views=stats["total_views"],
            gross_amount_cents=stats["gross_amount_cents"],
            unpaid_amount_cents=stats["unpaid_amount_cents"],
            paid_amount_cents=stats["paid_amount_cents"],
            unpaid_views=stats["unpaid_views"],
            accounts=stats["accounts"],
            clippers=stats["clippers"],
        ),
        clippers=clippers,
    )
