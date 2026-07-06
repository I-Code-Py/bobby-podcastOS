from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.database import SessionLocal
from app.modules.clippers.services import payout_service, view_refresh_service

log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _daily_refresh() -> None:
    log.info("Scheduled: starting daily view refresh")
    db = SessionLocal()
    try:
        stats = view_refresh_service.refresh_all(db)
        log.info("Daily refresh done: %s", stats)
    except Exception:
        log.exception("Daily refresh failed")
    finally:
        db.close()


def _weekly_payout() -> None:
    log.info("Scheduled: generating weekly payout cycle")
    db = SessionLocal()
    try:
        cycle = payout_service.generate_cycle(db)
        log.info("Payout cycle #%s generated, total %s cents", cycle.id, cycle.total_cents)
    except Exception:
        log.exception("Payout generation failed")
    finally:
        db.close()


def start() -> None:
    global _scheduler
    _scheduler = BackgroundScheduler(timezone="Europe/Paris")
    # Daily refresh at 03:00 Europe/Paris
    _scheduler.add_job(_daily_refresh, CronTrigger(hour=3, minute=0), id="daily_refresh")
    # Weekly payout recap Sunday 18:00 Europe/Paris
    _scheduler.add_job(
        _weekly_payout, CronTrigger(day_of_week="sun", hour=18, minute=0), id="weekly_payout"
    )
    _scheduler.start()
    log.info("Scheduler started")


def stop() -> None:
    if _scheduler:
        _scheduler.shutdown(wait=False)
