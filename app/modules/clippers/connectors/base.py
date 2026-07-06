from dataclasses import dataclass
from datetime import date


@dataclass
class VideoInfo:
    """Une vidéo publique trouvée sur le compte d'un clippeur."""

    platform_video_id: str
    url: str | None = None
    title: str | None = None
    view_count: int | None = None
    duration_seconds: int | None = None
    published_at: date | None = None
