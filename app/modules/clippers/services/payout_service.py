from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.settings_service import get_rate_cents
from app.modules.clippers.models import (
    Account,
    Clipper,
    PayoutCycle,
    PayoutLine,
    PayoutLineAccountDetail,
    PayoutLineAccountSnapshot,
)


def generate_cycle(db: Session, today: date | None = None) -> PayoutCycle:
    """Compute a new payout cycle snapshot (does NOT mark accounts as paid)."""
    today = today or date.today()
    rate_cents = get_rate_cents(db)

    # Period: last 7 days
    period_start = today - timedelta(days=6)
    period_end = today

    cycle = PayoutCycle(period_start=period_start, period_end=period_end)
    db.add(cycle)
    db.flush()

    clippers = db.query(Clipper).filter_by(active=True).all()
    cycle_total = 0

    for clipper in clippers:
        line = PayoutLine(
            cycle_id=cycle.id,
            clipper_id=clipper.id,
            clipper_name_snapshot=clipper.name,
        )
        db.add(line)
        db.flush()
        line_total = 0

        for account in clipper.accounts:
            end_views = account.latest_total_views
            start_views = account.views_at_last_payout_checkpoint
            delta = max(0, end_views - start_views)
            payout_cents = (delta * rate_cents) // 1000

            detail = PayoutLineAccountDetail(
                line_id=line.id,
                account_id=account.id,
                handle_snapshot=account.handle,
                platform_snapshot=account.platform.value,
                delta_views=delta,
                payout_cents=payout_cents,
            )
            db.add(detail)
            db.flush()

            snapshot = PayoutLineAccountSnapshot(
                detail_id=detail.id,
                start_views=start_views,
                end_views=end_views,
            )
            db.add(snapshot)
            line_total += payout_cents

        line.total_cents = line_total
        cycle_total += line_total

    cycle.total_cents = cycle_total
    db.commit()
    db.refresh(cycle)
    return cycle


def mark_paid(db: Session, line: PayoutLine) -> None:
    """Mark a payout line as paid and advance checkpoint to frozen end_views."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    line.paid_at = now

    for detail in line.account_details:
        if detail.snapshot and detail.account_id:
            account = db.get(Account, detail.account_id)
            if account:
                account.views_at_last_payout_checkpoint = detail.snapshot.end_views

    # Mark whole cycle paid if all lines are paid
    cycle = line.cycle
    if all(l.paid_at is not None for l in cycle.lines):
        cycle.paid_at = now

    db.commit()
