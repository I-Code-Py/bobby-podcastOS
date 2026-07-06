from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.modules.clippers.models import Account, AccountStatus, Clipper, Platform


_YT_PATTERNS = [
    re.compile(r"youtube\.com/@[\w.-]+"),
    re.compile(r"youtube\.com/channel/[\w-]+"),
    re.compile(r"youtube\.com/c/[\w.-]+"),
    re.compile(r"youtube\.com/user/[\w.-]+"),
]
_TIKTOK_PATTERN = re.compile(r"tiktok\.com/@[\w.-]+")
_IG_PATTERN = re.compile(
    r"instagram\.com/(?!reel/|reels/|p/|explore/|stories/)[\w.-]+"
)


def detect_platform(url: str) -> Platform | None:
    u = url.lower()
    if any(p.search(u) for p in _YT_PATTERNS):
        return Platform.youtube
    if _TIKTOK_PATTERN.search(u):
        return Platform.tiktok
    if _IG_PATTERN.search(u):
        return Platform.instagram
    return None


def extract_handle(url: str) -> str:
    """Best-effort handle extraction from profile URL."""
    url = url.rstrip("/")
    # @handle style
    m = re.search(r"@([\w.-]+)", url)
    if m:
        return m.group(1)
    return url.split("/")[-1]


def create_account(
    db: Session,
    clipper_id: int,
    profile_url: str,
) -> Account:
    platform = detect_platform(profile_url)
    if platform is None:
        raise ValueError(f"URL non reconnue: {profile_url}")

    existing = db.query(Account).filter_by(profile_url=profile_url).first()
    if existing:
        raise ValueError("Ce compte existe déjà")

    handle = extract_handle(profile_url)
    account = Account(
        clipper_id=clipper_id,
        platform=platform,
        profile_url=profile_url,
        handle=handle,
        status=AccountStatus.active,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def delete_account(db: Session, account_id: int) -> None:
    account = db.get(Account, account_id)
    if account:
        db.delete(account)
        db.commit()


def get_clipper_or_404(db: Session, clipper_id: int) -> Clipper:
    clipper = db.get(Clipper, clipper_id)
    if clipper is None:
        raise ValueError("Clipper introuvable")
    return clipper
