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


def test_clipper_daily_totals_carries_last_known_when_a_scrape_fails(db):
    """Un compte sans snapshot un jour donné ne doit pas être compté pour zéro.

    Cas réel : le scraping TikTok d'un clippeur a échoué deux jours d'affilée.
    En sommant naïvement les snapshots du jour, son total passait de 520 426 à
    35 684 puis remontait — soit, pour le rapport Discord hebdomadaire, un gain
    annoncé de +513 675 vues au lieu de +28 933.
    """
    clipper = Clipper(name="Test")
    db.add(clipper)
    db.flush()
    big = Account(clipper_id=clipper.id, platform="tiktok", profile_url="https://t/1")
    small = Account(clipper_id=clipper.id, platform="youtube", profile_url="https://y/1")
    db.add_all([big, small])
    db.flush()
    d1, d2, d3 = date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3)
    db.add_all([
        AccountViewSnapshot(account_id=big.id, total_views=484_742, captured_at=d1),
        AccountViewSnapshot(account_id=small.id, total_views=32_900, captured_at=d1),
        # d2 : le scrape du gros compte échoue — aucun snapshot pour lui.
        AccountViewSnapshot(account_id=small.id, total_views=32_900, captured_at=d2),
        AccountViewSnapshot(account_id=big.id, total_views=492_141, captured_at=d3),
        AccountViewSnapshot(account_id=small.id, total_views=32_900, captured_at=d3),
    ])
    db.commit()

    totals = dict(evolution_service.clipper_daily_totals(db, clipper.id))

    # d2 reporte le dernier relevé connu du gros compte, il ne l'oublie pas.
    assert totals[d2] == 484_742 + 32_900
    # La série ne peut pas régresser à cause d'un scrape raté.
    assert totals[d1] <= totals[d2] <= totals[d3]


def test_clipper_daily_totals_ignores_account_before_its_first_snapshot(db):
    """Avant son premier relevé, un compte n'existe pas : il compte pour zéro.

    C'est le seul cas où un compte manquant vaut réellement zéro — on ne peut
    pas reporter un passé qu'on n'a jamais mesuré.
    """
    clipper = Clipper(name="Test")
    db.add(clipper)
    db.flush()
    first = Account(clipper_id=clipper.id, platform="youtube", profile_url="https://y/1")
    later = Account(clipper_id=clipper.id, platform="tiktok", profile_url="https://t/1")
    db.add_all([first, later])
    db.flush()
    d1, d2 = date(2026, 7, 1), date(2026, 7, 2)
    db.add_all([
        AccountViewSnapshot(account_id=first.id, total_views=1000, captured_at=d1),
        # `later` n'est suivi qu'à partir de d2.
        AccountViewSnapshot(account_id=first.id, total_views=1200, captured_at=d2),
        AccountViewSnapshot(account_id=later.id, total_views=300, captured_at=d2),
    ])
    db.commit()

    totals = dict(evolution_service.clipper_daily_totals(db, clipper.id))

    assert totals[d1] == 1000
    assert totals[d2] == 1500


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
