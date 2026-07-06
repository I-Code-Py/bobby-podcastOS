from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.modules.clippers.models import (
    ACCOUNT_STATUS_ARCHIVED,
    PAYMENT_METHODS,
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


def list_clipper_names(db: Session) -> list[Clipper]:
    """Liste légère (id + nom) pour peupler un menu déroulant, sans charger
    les comptes/vidéos de chaque clippeur."""
    return list(db.scalars(select(Clipper).order_by(Clipper.name)))


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


def set_payment_info(db: Session, clipper: Clipper, method: str | None,
                     handle: str | None) -> None:
    """Enregistre le moyen de paiement du clippeur. Une méthode vide efface le
    moyen de paiement existant."""
    from app.modules.clippers.services import payment_service

    method = (method or "").strip().lower()
    if method not in PAYMENT_METHODS:
        clipper.payment_method = None
        clipper.payment_handle = None
        db.commit()
        return
    normalized = payment_service.normalize_handle(handle)
    if not normalized:
        raise ValueError("Le pseudo (ou le lien de paiement) est obligatoire")
    clipper.payment_method = method
    clipper.payment_handle = normalized
    db.commit()


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


def delete_clipper(db: Session, clipper: Clipper) -> None:
    """Supprime définitivement le clippeur et tous ses comptes (avec leur
    historique). Refuse si un seul de ses comptes apparaît déjà dans un
    récap de paiement — dans ce cas, désactivez le clippeur à la place."""
    from app.modules.clippers.services.account_service import (
        _assert_account_deletable,
        _delete_account_no_commit,
    )

    for account in clipper.accounts:
        _assert_account_deletable(db, account)
    for account in list(clipper.accounts):
        _delete_account_no_commit(db, account)
    db.delete(clipper)
    db.commit()
