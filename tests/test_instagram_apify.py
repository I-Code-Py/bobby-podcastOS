from datetime import date

import pytest

from app.modules.clippers.connectors.errors import ConnectorError
from app.modules.clippers.connectors.instagram_apify import (
    _extract_username,
    _item_to_video,
    fetch_instagram_profile_videos_apify,
)


class TestExtractUsername:
    def test_simple_profile(self):
        assert _extract_username("https://www.instagram.com/bobby.clipp/") == "bobby.clipp"

    def test_without_trailing_slash(self):
        assert _extract_username("https://instagram.com/clip2bobbysan") == "clip2bobbysan"

    def test_strips_at_and_query(self):
        assert _extract_username("https://www.instagram.com/@bobby_reels4?hl=fr") == "bobby_reels4"

    def test_reserved_segment_is_not_a_username(self):
        # une URL de post ne doit pas être prise pour un profil
        assert _extract_username("https://www.instagram.com/reel/DZ0uXVgqjx4/") is None

    def test_garbage(self):
        assert _extract_username("https://example.com/whatever") is None


class TestItemToVideo:
    def test_maps_play_count_as_views(self):
        v = _item_to_video({
            "shortCode": "DZ0uXVgqjx4",
            "url": "https://www.instagram.com/p/DZ0uXVgqjx4/",
            "videoPlayCount": 138,
            "videoViewCount": 54,
            "caption": "hello",
            "timestamp": "2026-06-20T22:05:40.000Z",
            "videoDuration": 12.5,
        })
        assert v.platform_video_id == "DZ0uXVgqjx4"
        assert v.view_count == 138  # playCount prioritaire sur viewCount
        assert v.url.endswith("/DZ0uXVgqjx4/")
        assert v.title == "hello"
        assert v.published_at == date(2026, 6, 20)
        assert v.duration_seconds == 12

    def test_falls_back_to_view_count(self):
        v = _item_to_video({"id": "123", "videoViewCount": 99})
        assert v.view_count == 99
        assert v.platform_video_id == "123"

    def test_no_views_is_none(self):
        v = _item_to_video({"shortCode": "abc"})
        assert v.view_count is None

    def test_missing_id_is_dropped(self):
        assert _item_to_video({"videoPlayCount": 10}) is None

    def test_caption_is_truncated(self):
        v = _item_to_video({"shortCode": "x", "caption": "a" * 500})
        assert len(v.title) == 300


def test_fetch_requires_token(monkeypatch):
    """Sans token, on lève une ConnectorError claire (repli, pas de crash)."""
    from app.modules.clippers.connectors import instagram_apify

    class _S:
        apify_token = ""
        instagram_scan_days = 30
        instagram_apify_results_limit = 200

    monkeypatch.setattr(instagram_apify, "get_settings", lambda: _S())
    with pytest.raises(ConnectorError):
        fetch_instagram_profile_videos_apify("https://www.instagram.com/bobby.clipp/")
