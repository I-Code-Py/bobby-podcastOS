"""Statistiques globales de la campagne (vues + argent).

Écrit un petit JSON `data/shared/campaign_stats.json` que le bot Discord lit
(dossier monté en lecture seule) pour la commande `/stats`. Rafraîchi au
démarrage de l'app et après chaque scrape quotidien des vues.
"""

import json
import logging
import os
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.settings_service import get_rate_cents
from app.modules.clippers.models import ACCOUNT_STATUS_ARCHIVED, Account, Clipper
from app.modules.clippers.services.payout_service import amount_cents_for_views

logger = logging.getLogger(__name__)

STATS_DIR = os.path.join("data", "shared")
STATS_PATH = os.path.join(STATS_DIR, "campaign_stats.json")


def campaign_stats(db: Session) -> dict:
    """Totaux campagne : vues cumulées, valeur, déjà payé, reste à verser."""
    rate = get_rate_cents(db)
    accounts = db.scalars(
        select(Account)
        .where(Account.status != ACCOUNT_STATUS_ARCHIVED)
        .options(selectinload(Account.snapshots))
    ).all()

    total_views = 0
    unpaid_views = 0
    for acc in accounts:
        views = acc.latest_total_views
        total_views += views
        unpaid_views += max(0, views - acc.views_at_last_payout_checkpoint)

    gross = amount_cents_for_views(total_views, rate)
    unpaid = amount_cents_for_views(unpaid_views, rate)

    clippers = db.scalar(
        select(func.count()).select_from(Clipper).where(Clipper.active.is_(True))
    ) or 0

    return {
        "total_views": total_views,
        "rate_cents_per_1000": rate,
        "gross_amount_cents": gross,
        "unpaid_views": unpaid_views,
        "unpaid_amount_cents": unpaid,
        "paid_amount_cents": gross - unpaid,
        "accounts": len(accounts),
        "clippers": int(clippers),
    }


def write_campaign_stats(db: Session) -> dict:
    """Calcule et écrit le JSON partagé. Retourne les stats."""
    stats = campaign_stats(db)
    stats["generated_at"] = datetime.now(timezone.utc).isoformat()
    try:
        os.makedirs(STATS_DIR, exist_ok=True)
        with open(STATS_PATH, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
        logger.info("campaign_stats écrit (%s vues).", stats["total_views"])
    except Exception as exc:
        logger.warning("Impossible d'écrire campaign_stats : %s", exc)
    return stats
