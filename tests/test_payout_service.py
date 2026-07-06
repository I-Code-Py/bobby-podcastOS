from datetime import date, timedelta

from app.core import settings_service
from app.modules.clippers.models import (
    Account,
    AccountViewSnapshot,
    Clipper,
)
from app.modules.clippers.services import payout_service


def _clipper_with_accounts(db, views_by_platform: dict[str, int],
                           captured: date | None = None) -> Clipper:
    clipper = Clipper(name="Test Clippeur")
    db.add(clipper)
    db.flush()
    for platform, total in views_by_platform.items():
        account = Account(clipper_id=clipper.id, platform=platform,
                          profile_url=f"https://{platform}.com/@test")
        db.add(account)
        db.flush()
        db.add(AccountViewSnapshot(account_id=account.id, total_views=total,
                                   video_count=3, captured_at=captured or date.today()))
    db.commit()
    return clipper


def test_cycle_sums_account_views_at_rate(db):
    # 1€/1000 vues : 10 000 (YT) + 5 000 (TT) + 3 000 (IG) = 18 000 → 18 €
    _clipper_with_accounts(db, {"youtube": 10_000, "tiktok": 5_000, "instagram": 3_000})
    cycle = payout_service.generate_cycle(db)

    assert len(cycle.lines) == 1
    line = cycle.lines[0]
    assert line.delta_views == 18_000
    assert line.amount_due_cents == 1_800
    assert len(line.account_details) == 3


def test_custom_rate_is_applied(db):
    settings_service.set_rate_cents(db, 250)  # 2,50 € / 1000 vues
    _clipper_with_accounts(db, {"youtube": 4_000})
    cycle = payout_service.generate_cycle(db)
    assert cycle.lines[0].amount_due_cents == 1_000


def test_mark_paid_freezes_checkpoint_and_next_cycle_counts_only_new_views(db):
    clipper = _clipper_with_accounts(db, {"youtube": 10_000})
    line = payout_service.generate_cycle(db).lines[0]
    payout_service.mark_paid(db, line)

    account = clipper.accounts[0]
    assert account.views_at_last_payout_checkpoint == 10_000

    # Le compte passe à 12 500 vues le lendemain
    db.add(AccountViewSnapshot(account_id=account.id, total_views=12_500,
                               video_count=4, captured_at=date.today() + timedelta(days=1)))
    db.commit()

    new_line = payout_service.generate_cycle(db).lines[0]
    assert new_line.delta_views == 2_500
    assert new_line.amount_due_cents == 250


def test_generation_without_payment_supersedes_previous(db):
    _clipper_with_accounts(db, {"tiktok": 8_000})
    payout_service.generate_cycle(db)
    second = payout_service.generate_cycle(db)
    assert second.lines[0].delta_views == 8_000

    from sqlalchemy import select

    from app.modules.clippers.models import PayoutLine

    lines = db.scalars(select(PayoutLine).order_by(PayoutLine.id)).all()
    assert [l.status for l in lines] == ["superseded", "pending"]
    assert lines[0].superseded_by_line_id == second.lines[0].id


def test_view_count_drop_is_clamped_to_zero(db):
    clipper = _clipper_with_accounts(db, {"youtube": 10_000})
    payout_service.mark_paid(db, payout_service.generate_cycle(db).lines[0])

    account = clipper.accounts[0]
    db.add(AccountViewSnapshot(account_id=account.id, total_views=9_000,
                               video_count=2, captured_at=date.today() + timedelta(days=1)))
    db.commit()

    cycle = payout_service.generate_cycle(db)
    assert cycle.lines[0].delta_views == 0
    assert cycle.lines[0].amount_due_cents == 0


def test_mark_paid_twice_is_rejected(db):
    _clipper_with_accounts(db, {"youtube": 1_000})
    line = payout_service.generate_cycle(db).lines[0]
    payout_service.mark_paid(db, line)

    import pytest

    with pytest.raises(ValueError):
        payout_service.mark_paid(db, line)


def test_live_estimate_matches_unpaid_views(db):
    clipper = _clipper_with_accounts(db, {"youtube": 6_000, "tiktok": 4_000})
    views, cents = payout_service.live_unpaid_estimate_cents(db, clipper)
    assert views == 10_000
    assert cents == 1_000
