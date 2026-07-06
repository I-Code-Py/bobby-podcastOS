from __future__ import annotations

from sqlalchemy.orm import Session

from app.modules.clippers.models import AppSetting

RATE_KEY = "rate_cents_per_1000_views"
MIN_VIEWS_KEY = "min_views_per_video"
USD_EUR_RATE_KEY = "usd_eur_rate"          # how many EUR per 1 USD (e.g. 0.92)
DEFAULT_RATE_CENTS = 100   # 1 € per 1000 views
DEFAULT_MIN_VIEWS = 1000
DEFAULT_USD_EUR_RATE = 92  # stored as int * 100 to avoid floats — 92 = 0.92


def _get(db: Session, key: str, default: int) -> int:
    row = db.get(AppSetting, key)
    return int(row.value) if row else default


def _set(db: Session, key: str, value: int) -> None:
    row = db.get(AppSetting, key)
    if row:
        row.value = str(value)
    else:
        db.add(AppSetting(key=key, value=str(value)))
    db.commit()


def get_rate_cents(db: Session) -> int:
    return _get(db, RATE_KEY, DEFAULT_RATE_CENTS)


def set_rate_cents(db: Session, cents: int) -> None:
    _set(db, RATE_KEY, cents)


def get_min_views_per_video(db: Session) -> int:
    return _get(db, MIN_VIEWS_KEY, DEFAULT_MIN_VIEWS)


def set_min_views_per_video(db: Session, min_views: int) -> None:
    _set(db, MIN_VIEWS_KEY, min_views)


def get_usd_eur_rate(db: Session) -> float:
    """Returns EUR per 1 USD (e.g. 0.92)."""
    return _get(db, USD_EUR_RATE_KEY, DEFAULT_USD_EUR_RATE) / 100.0


def set_usd_eur_rate(db: Session, rate_float: float) -> None:
    """Store rate as int * 100 (e.g. 0.92 → 92)."""
    _set(db, USD_EUR_RATE_KEY, int(round(rate_float * 100)))
