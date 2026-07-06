"""Jobs planifiés du module clippers.

- refresh quotidien des vues à 03:00 (heure creuse) : scraping de tous les
  comptes actifs
- récap de paiement hebdomadaire le dimanche à 18:00

Les mêmes fonctions sont appelables depuis la CLI et les boutons de l'UI.
"""

import logging

from apscheduler.schedulers.base import BaseScheduler
from apscheduler.triggers.cron import CronTrigger

from app.db import session_scope

logger = logging.getLogger(__name__)


def refresh_all_views() -> dict:
    from app.modules.clippers.services import view_refresh_service

    db = session_scope()
    try:
        return view_refresh_service.refresh_all(db)
    finally:
        db.close()


def generate_weekly_payout() -> int:
    from app.modules.clippers.services import payout_service

    db = session_scope()
    try:
        cycle = payout_service.generate_cycle(db)
        return cycle.id
    finally:
        db.close()


def register(scheduler: BaseScheduler) -> None:
    scheduler.add_job(
        refresh_all_views,
        CronTrigger(hour=3, minute=0),
        id="clippers.refresh_all_views",
        replace_existing=True,
        misfire_grace_time=3600 * 6,
        coalesce=True,
    )
    scheduler.add_job(
        generate_weekly_payout,
        CronTrigger(day_of_week="sun", hour=18, minute=0),
        id="clippers.generate_weekly_payout",
        replace_existing=True,
        misfire_grace_time=3600 * 6,
        coalesce=True,
    )
