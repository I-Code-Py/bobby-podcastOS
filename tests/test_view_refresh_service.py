from datetime import date, timedelta

from app.modules.clippers.connectors.base import VideoInfo
from app.modules.clippers.connectors.errors import ConnectorError
from app.modules.clippers.models import (
    ACCOUNT_STATUS_MANUAL_REQUIRED,
    Account,
    Clipper,
)
from app.modules.clippers.services import view_refresh_service


def _account(db) -> Account:
    clipper = Clipper(name="Test")
    db.add(clipper)
    db.flush()
    account = Account(clipper_id=clipper.id, platform="tiktok",
                      profile_url="https://tiktok.com/@test")
    db.add(account)
    db.commit()
    return account


def _patch_fetch(monkeypatch, result):
    # On remplace le wrapper avec retry pour éviter les temporisations tenacity
    def fake(profile_url, platform):
        if isinstance(result, Exception):
            raise result
        return result
    monkeypatch.setattr(view_refresh_service, "_fetch_with_retry", fake)


def test_refresh_counts_only_videos_above_threshold(db, monkeypatch):
    account = _account(db)
    # Seuil par défaut = 1000. v_low (800) et v_none ne sont pas comptées.
    _patch_fetch(monkeypatch, [
        VideoInfo(platform_video_id="v1", url="u1", title="A", view_count=1000),
        VideoInfo(platform_video_id="v2", url="u2", title="B", view_count=2500),
        VideoInfo(platform_video_id="v_low", url="u3", title="C", view_count=800),
        VideoInfo(platform_video_id="v_none", url="u4", title="D", view_count=None),
    ])

    ok = view_refresh_service.refresh_account(db, account)
    assert ok is True
    # 1000 + 2500 comptées ; 800 sous le seuil, None ignorée
    assert account.latest_total_views == 3500
    assert account.latest_video_count == 2  # nombre de vidéos comptabilisées
    assert len(account.videos) == 4  # toutes les vidéos restent enregistrées


def test_refresh_records_per_video_daily_snapshot(db, monkeypatch):
    account = _account(db)
    _patch_fetch(monkeypatch, [VideoInfo(platform_video_id="v1", view_count=1200)])
    view_refresh_service.refresh_account(db, account, captured_at=date.today())

    _patch_fetch(monkeypatch, [VideoInfo(platform_video_id="v1", view_count=1900)])
    view_refresh_service.refresh_account(db, account,
                                         captured_at=date.today() + timedelta(days=1))

    video = account.videos[0]
    assert len(video.snapshots) == 2
    assert [s.view_count for s in video.snapshots] == [1200, 1900]


def test_custom_threshold_is_applied(db, monkeypatch):
    from app.core import settings_service

    settings_service.set_min_views_per_video(db, 5000)
    account = _account(db)
    _patch_fetch(monkeypatch, [
        VideoInfo(platform_video_id="v1", view_count=4000),   # sous 5000 → exclue
        VideoInfo(platform_video_id="v2", view_count=6000),   # comptée
    ])
    view_refresh_service.refresh_account(db, account)
    assert account.latest_total_views == 6000
    assert account.latest_video_count == 1


def test_refresh_updates_existing_video_counts(db, monkeypatch):
    account = _account(db)
    _patch_fetch(monkeypatch, [VideoInfo(platform_video_id="v1", view_count=1000)])
    view_refresh_service.refresh_account(db, account, captured_at=date.today())

    _patch_fetch(monkeypatch, [VideoInfo(platform_video_id="v1", view_count=1800)])
    view_refresh_service.refresh_account(db, account,
                                         captured_at=date.today() + timedelta(days=1))

    assert len(account.videos) == 1  # pas de doublon
    assert account.latest_total_views == 1800


def test_repeated_failures_flip_to_manual_required(db, monkeypatch):
    account = _account(db)
    _patch_fetch(monkeypatch, ConnectorError("blocage"))
    for _ in range(3):
        assert view_refresh_service.refresh_account(db, account) is False
    assert account.status == ACCOUNT_STATUS_MANUAL_REQUIRED
    assert account.consecutive_failures == 3
