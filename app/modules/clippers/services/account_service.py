import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.clippers.models import (
    ACCOUNT_STATUS_ACTIVE,
    PLATFORM_INSTAGRAM,
    PLATFORM_TIKTOK,
    PLATFORM_YOUTUBE,
    SNAPSHOT_SOURCE_MANUAL,
    Account,
    AccountViewSnapshot,
    Clipper,
)

# Détection de la plateforme + du handle à partir de l'URL d'un profil/compte
_YOUTUBE_RE = re.compile(
    r"youtube\.com/(?:(@[\w.-]+)|channel/([\w-]+)|c/([\w.-]+)|user/([\w.-]+))"
)
_TIKTOK_RE = re.compile(r"tiktok\.com/(@[\w.-]+)")
_INSTAGRAM_RE = re.compile(r"instagram\.com/([\w.][\w.-]*)")

# Segments Instagram qui ne sont pas des profils
_INSTAGRAM_RESERVED = {"reel", "reels", "p", "explore", "stories", "tv"}


def detect_account(url: str) -> tuple[str, str | None]:
    """Déduit (plateforme, handle) de l'URL d'un compte."""
    url = url.strip()
    match = _YOUTUBE_RE.search(url)
    if match:
        handle = next((g for g in match.groups() if g), None)
        return PLATFORM_YOUTUBE, handle
    match = _TIKTOK_RE.search(url)
    if match:
        return PLATFORM_TIKTOK, match.group(1)
    match = _INSTAGRAM_RE.search(url)
    if match and match.group(1).lower() not in _INSTAGRAM_RESERVED:
        return PLATFORM_INSTAGRAM, match.group(1)
    raise ValueError(
        "URL de compte non reconnue : attendu une chaîne YouTube "
        "(youtube.com/@… ou /channel/…), un profil TikTok (tiktok.com/@…) "
        "ou un profil Instagram (instagram.com/…)"
    )


def add_account(db: Session, clipper: Clipper, url: str) -> Account:
    url = url.strip()
    existing = db.scalar(select(Account).where(Account.profile_url == url))
    if existing:
        raise ValueError(
            f"Ce compte est déjà assigné au clippeur « {existing.clipper.name} »"
        )
    platform, handle = detect_account(url)
    account = Account(
        clipper_id=clipper.id, platform=platform, profile_url=url, handle=handle
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def record_manual_total(db: Session, account: Account, total_views: int,
                        captured_at: date | None = None) -> None:
    """Saisie manuelle du total de vues du compte (repli quand le scraping
    échoue, ex. Instagram)."""
    if total_views < 0:
        raise ValueError("Le nombre de vues ne peut pas être négatif")
    captured_at = captured_at or date.today()
    snapshot = db.scalar(
        select(AccountViewSnapshot).where(
            AccountViewSnapshot.account_id == account.id,
            AccountViewSnapshot.captured_at == captured_at,
        )
    )
    if snapshot is None:
        snapshot = AccountViewSnapshot(account_id=account.id, captured_at=captured_at,
                                       video_count=account.latest_video_count)
        db.add(snapshot)
    snapshot.total_views = total_views
    snapshot.source = SNAPSHOT_SOURCE_MANUAL
    account.consecutive_failures = 0
    account.last_fetch_status = "manual"
    if account.status != ACCOUNT_STATUS_ACTIVE:
        account.status = ACCOUNT_STATUS_ACTIVE
    db.commit()


def archive_account(db: Session, account: Account) -> None:
    from app.modules.clippers.models import ACCOUNT_STATUS_ARCHIVED

    account.status = ACCOUNT_STATUS_ARCHIVED
    db.commit()
