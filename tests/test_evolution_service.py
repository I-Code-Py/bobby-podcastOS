from datetime import date, timedelta

from app.modules.clippers.models import (
    Account,
    AccountVideo,
    AccountVideoSnapshot,
    AccountViewSnapshot,
    Clipper,
)
from app.modules.clippers.services import evolution_service


def test_clipper_daily_totals_sums_accounts_per_day(db):
    clipper = Clipper(name="Test")
    db.add(clipper)
    db.flush()
    a1 = Account(clipper_id=clipper.id, platform="youtube", profile_url="https://y/1")
    a2 = Account(clipper_id=clipper.id, platform="tiktok", profile_url="https://t/2")
    db.add_all([a1, a2])
    db.flush()
    d1, d2 = date(2026, 7, 1), date(2026, 7, 2)
    db.add_all([
        AccountViewSnapshot(account_id=a1.id, total_views=1000, captured_at=d1),
        AccountViewSnapshot(account_id=a2.id, total_views=500, captured_at=d1),
        AccountViewSnapshot(account_id=a1.id, total_views=1500, captured_at=d2),
        AccountViewSnapshot(account_id=a2.id, total_views=900, captured_at=d2),
    ])
    db.commit()

    totals = evolution_service.clipper_daily_totals(db, clipper.id)
    assert totals == [(d1, 1500), (d2, 2400)]


def test_video_histories_reports_growth(db):
    clipper = Clipper(name="Test")
    db.add(clipper)
    db.flush()
    account = Account(clipper_id=clipper.id, platform="tiktok",
                      profile_url="https://t/1")
    db.add(account)
    db.flush()
    video = AccountVideo(account_id=account.id, platform_video_id="v1",
                         title="Clip", view_count=2000)
    db.add(video)
    db.flush()
    db.add_all([
        AccountVideoSnapshot(account_video_id=video.id, view_count=1200,
                             captured_at=date.today() - timedelta(days=2)),
        AccountVideoSnapshot(account_video_id=video.id, view_count=2000,
                             captured_at=date.today()),
    ])
    db.commit()

    histories = evolution_service.video_histories(db, account.id)
    assert len(histories) == 1
    assert histories[0]["current"] == 2000
    assert histories[0]["growth"] == 800
    assert histories[0]["points"] == [1200, 2000]
