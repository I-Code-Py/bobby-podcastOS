import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import get_settings

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def build_scheduler() -> BackgroundScheduler:
    """Construit le scheduler et laisse chaque module y enregistrer ses jobs."""
    settings = get_settings()
    scheduler = BackgroundScheduler(timezone=ZoneInfo(settings.timezone))

    from app.modules.clippers import jobs as clippers_jobs

    clippers_jobs.register(scheduler)
    return scheduler


def start_scheduler() -> BackgroundScheduler | None:
    global _scheduler
    settings = get_settings()
    if not settings.scheduler_enabled:
        logger.info("Scheduler désactivé (SCHEDULER_ENABLED=false)")
        return None
    _scheduler = build_scheduler()
    _scheduler.start()
    for job in _scheduler.get_jobs():
        logger.info("Job planifié : %s (%s)", job.id, job.trigger)
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def run_in_background(func, *args, job_id: str | None = None) -> bool:
    """Exécute une fonction immédiatement en arrière-plan via le scheduler
    (utilisé par les boutons « maintenant » de l'UI). Retourne False si le
    scheduler ne tourne pas (l'appelant exécutera alors en synchrone)."""
    if _scheduler is None:
        return False
    _scheduler.add_job(func, args=args, id=job_id, replace_existing=True,
                       misfire_grace_time=3600)
    return True
