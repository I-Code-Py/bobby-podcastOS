import pytest

from app.modules.clippers.connectors.account_videos import _entry_to_video_info
from app.modules.clippers.services.account_service import detect_account


class TestDetectAccount:
    def test_youtube_handle(self):
        assert detect_account("https://www.youtube.com/@BobbySanClips") == (
            "youtube", "@BobbySanClips",
        )

    def test_youtube_channel_id(self):
        platform, handle = detect_account(
            "https://youtube.com/channel/UCabc123DEF456ghi789JKL"
        )
        assert platform == "youtube"
        assert handle == "UCabc123DEF456ghi789JKL"

    def test_tiktok_profile(self):
        assert detect_account("https://www.tiktok.com/@momoclips") == (
            "tiktok", "@momoclips",
        )

    def test_instagram_profile(self):
        assert detect_account("https://www.instagram.com/momoclips/") == (
            "instagram", "momoclips",
        )

    def test_instagram_reel_is_not_a_profile(self):
        # Une URL de reel individuel ne doit pas être prise pour un profil
        with pytest.raises(ValueError):
            detect_account("https://www.instagram.com/reel/C8abcDEfGhI/")

    def test_unknown_url_raises(self):
        with pytest.raises(ValueError):
            detect_account("https://example.com/whatever")


class TestEntryToVideoInfo:
    def test_maps_all_fields(self):
        entry = {
            "id": "abc123",
            "url": "https://youtube.com/shorts/abc123",
            "title": "Bobby raconte tout",
            "view_count": 45000,
            "duration": 58,
            "upload_date": "20260701",
        }
        video = _entry_to_video_info(entry)
        assert video.platform_video_id == "abc123"
        assert video.view_count == 45000
        assert video.duration_seconds == 58
        assert video.published_at is not None
        assert video.published_at.year == 2026

    def test_missing_view_count_is_none(self):
        video = _entry_to_video_info({"id": "x1", "title": "sans vues"})
        assert video.view_count is None
        assert video.platform_video_id == "x1"

    def test_entry_without_id_is_skipped(self):
        assert _entry_to_video_info({"title": "orphelin"}) is None
