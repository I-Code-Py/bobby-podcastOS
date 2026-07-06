from sqlalchemy.orm import Session

from app.modules.clippers.models import AppSetting

RATE_KEY = "rate_cents_per_1000_views"
DEFAULT_RATE_CENTS = 100  # 1 € / 1000 vues

MIN_VIEWS_KEY = "min_views_per_video"
DEFAULT_MIN_VIEWS = 1000  # vidéos sous ce seuil : non comptabilisées


def get_setting(db: Session, key: str, default: str | None = None) -> str | None:
    row = db.get(AppSetting, key)
    return row.value if row else default


def set_setting(db: Session, key: str, value: str) -> None:
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=value))
    else:
        row.value = value
    db.commit()


def get_rate_cents(db: Session) -> int:
    value = get_setting(db, RATE_KEY)
    if value is None:
        set_setting(db, RATE_KEY, str(DEFAULT_RATE_CENTS))
        return DEFAULT_RATE_CENTS
    return int(value)


def set_rate_cents(db: Session, cents: int) -> None:
    if cents <= 0:
        raise ValueError("Le taux doit être strictement positif")
    set_setting(db, RATE_KEY, str(cents))


def get_min_views_per_video(db: Session) -> int:
    value = get_setting(db, MIN_VIEWS_KEY)
    if value is None:
        set_setting(db, MIN_VIEWS_KEY, str(DEFAULT_MIN_VIEWS))
        return DEFAULT_MIN_VIEWS
    return int(value)


def set_min_views_per_video(db: Session, min_views: int) -> None:
    if min_views < 0:
        raise ValueError("Le seuil de vues ne peut pas être négatif")
    set_setting(db, MIN_VIEWS_KEY, str(min_views))
