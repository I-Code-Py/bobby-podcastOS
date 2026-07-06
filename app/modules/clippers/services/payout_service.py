"""Génération des récaps hebdomadaires et suivi de ce qui a été payé.

Chaque compte porte un checkpoint `views_at_last_payout_checkpoint` (les vues
déjà rémunérées). Un récap calcule pour chaque compte le delta
`total de vues actuel - checkpoint` — le checkpoint n'est PAS modifié à la
génération, seulement quand le manager clique « Marquer payé » : les valeurs
`end_views` figées dans le récap deviennent alors le nouveau checkpoint. Ainsi
une vue n'est jamais payée deux fois, et rien n'est perdu si un récap reste
impayé plusieurs semaines (le suivant l'englobe et l'ancien passe en
`superseded`).
"""

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.settings_service import get_rate_cents
from app.modules.clippers.models import (
    ACCOUNT_STATUS_ARCHIVED,
    PAYOUT_PENDING,
    PAYOUT_SUPERSEDED,
    Account,
    Clipper,
    PayoutCycle,
    PayoutLine,
    PayoutLineAccountDetail,
    PayoutLineAccountSnapshot,
)

logger = logging.getLogger(__name__)


def amount_cents_for_views(views: int, rate_cents_per_1000: int) -> int:
    return views * rate_cents_per_1000 // 1000


def generate_cycle(db: Session, today: date | None = None) -> PayoutCycle:
    """Génère le récap hebdomadaire (déclenché le dimanche 18h ou à la main)."""
    today = today or date.today()
    week_start = today - timedelta(days=6)
    rate = get_rate_cents(db)

    cycle = PayoutCycle(week_start_date=week_start, week_end_date=today)
    db.add(cycle)
    db.flush()

    clippers = db.scalars(
        select(Clipper).where(Clipper.active).order_by(Clipper.name)
    ).all()

    for clipper in clippers:
        accounts = db.scalars(
            select(Account)
            .where(Account.clipper_id == clipper.id,
                   Account.status != ACCOUNT_STATUS_ARCHIVED)
            .options(selectinload(Account.snapshots))
        ).all()
        if not accounts:
            continue

        line_delta = 0
        details: list[PayoutLineAccountDetail] = []
        snapshots: list[PayoutLineAccountSnapshot] = []
        for account in accounts:
            end_views = account.latest_total_views
            start_views = account.views_at_last_payout_checkpoint
            # clamp ≥ 0 : tolère une baisse de compteur (vidéo supprimée, bug)
            delta = max(0, end_views - start_views)
            snapshots.append(PayoutLineAccountSnapshot(
                account_id=account.id, start_views=start_views,
                end_views=end_views, delta_views=delta,
            ))
            if delta > 0:
                details.append(PayoutLineAccountDetail(
                    account_id=account.id, delta_views=delta,
                    amount_cents=amount_cents_for_views(delta, rate),
                ))
            line_delta += delta

        line = PayoutLine(
            payout_cycle_id=cycle.id, clipper_id=clipper.id,
            delta_views=line_delta,
            amount_due_cents=amount_cents_for_views(line_delta, rate),
        )
        db.add(line)
        db.flush()
        for detail in details:
            detail.payout_line_id = line.id
            db.add(detail)
        for snapshot in snapshots:
            snapshot.payout_line_id = line.id
            db.add(snapshot)

        # Le nouveau récap englobe tout l'impayé antérieur du clippeur
        previous_pending = db.scalars(
            select(PayoutLine).where(
                PayoutLine.clipper_id == clipper.id,
                PayoutLine.status == PAYOUT_PENDING,
                PayoutLine.id != line.id,
            )
        ).all()
        for old_line in previous_pending:
            old_line.status = PAYOUT_SUPERSEDED
            old_line.superseded_by_line_id = line.id

    db.commit()
    logger.info("Récap généré : cycle #%d (%s → %s)", cycle.id, week_start, today)
    return cycle


def mark_paid(db: Session, line: PayoutLine) -> None:
    """Fige les checkpoints avec les end_views enregistrés dans la ligne
    (et non les vues « live », pour éviter toute course avec un refresh)."""
    if line.status != PAYOUT_PENDING:
        raise ValueError("Seule une ligne en attente peut être marquée payée")
    for snapshot in line.account_snapshots:
        account = snapshot.account
        if snapshot.end_views > account.views_at_last_payout_checkpoint:
            account.views_at_last_payout_checkpoint = snapshot.end_views
    from app.modules.clippers.models import PAYOUT_PAID

    line.status = PAYOUT_PAID
    line.paid_at = datetime.now(timezone.utc)
    db.commit()


def list_cycles(db: Session) -> list[PayoutCycle]:
    return list(db.scalars(
        select(PayoutCycle).order_by(PayoutCycle.generated_at.desc())
    ))


def live_unpaid_estimate_cents(db: Session, clipper: Clipper) -> tuple[int, int]:
    """Estimation temps réel (vues non payées, montant) sans générer de récap."""
    rate = get_rate_cents(db)
    unpaid_views = 0
    for account in clipper.accounts:
        if account.status == ACCOUNT_STATUS_ARCHIVED:
            continue
        unpaid_views += max(
            0, account.latest_total_views - account.views_at_last_payout_checkpoint
        )
    return unpaid_views, amount_cents_for_views(unpaid_views, rate)
