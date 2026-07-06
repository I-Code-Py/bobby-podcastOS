from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.modules.clippers.models import (
    ACCOUNT_STATUS_ARCHIVED,
    Account,
    Clipper,
)


def _clipper_load_options():
    return (
        selectinload(Clipper.accounts).selectinload(Account.snapshots),
        selectinload(Clipper.accounts).selectinload(Account.videos),
    )


def list_clippers(db: Session) -> list[Clipper]:
    return list(db.scalars(
        select(Clipper)
        .order_by(Clipper.active.desc(), Clipper.name)
        .options(selectinload(Clipper.accounts).selectinload(Account.snapshots))
    ))


def get_clipper(db: Session, clipper_id: int) -> Clipper | None:
    return db.scalar(
        select(Clipper)
        .where(Clipper.id == clipper_id)
        .options(*_clipper_load_options())
    )


def create_clipper(db: Session, name: str, notes: str | None = None) -> Clipper:
    name = name.strip()
    if not name:
        raise ValueError("Le nom du clippeur est obligatoire")
    if db.scalar(select(Clipper).where(Clipper.name == name)):
        raise ValueError(f"Un clippeur nommé « {name} » existe déjà")
    clipper = Clipper(name=name, notes=notes or None)
    db.add(clipper)
    db.commit()
    db.refresh(clipper)
    return clipper


def total_views(clipper: Clipper) -> int:
    return sum(
        account.latest_total_views
        for account in clipper.accounts
        if account.status != ACCOUNT_STATUS_ARCHIVED
    )


def active_accounts(clipper: Clipper) -> list[Account]:
    accounts = [a for a in clipper.accounts if a.status != ACCOUNT_STATUS_ARCHIVED]
    accounts.sort(key=lambda a: (a.platform, a.id))
    return accounts
