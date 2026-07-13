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
    from app.modules.clippers.services import stats_service, view_refresh_service

    db = session_scope()
    try:
        result = view_refresh_service.refresh_all(db)
        try:
            stats_service.write_campaign_stats(db)
        except Exception:
            pass
        return result
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


def send_weekly_reports() -> dict:
    from app.modules.clippers.services import weekly_report_service

    db = session_scope()
    try:
        return weekly_report_service.send_all_reports(db)
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
    # Rapports Discord (clippers + staff) le dimanche 20h, après le récap de 18h
    scheduler.add_job(
        send_weekly_reports,
        CronTrigger(day_of_week="sun", hour=20, minute=0),
        id="clippers.send_weekly_reports",
        replace_existing=True,
        misfire_grace_time=3600 * 6,
        coalesce=True,
    )
