from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./data/app.db"
    secret_key: str = "dev-secret-change-me"
    session_secure: bool = False

    youtube_api_key: str = ""
    scrape_delay_seconds: float = 5.0
    instagram_delay_seconds: float = 12.0
    # Fichier de cookies (format Netscape) exporté depuis un navigateur connecté.
    # Indispensable pour Instagram : yt-dlp ne peut pas lister les vidéos d'un
    # profil de façon anonyme (Instagram bloque cet accès sans session).
    cookies_file: str = ""

    timezone: str = "Europe/Paris"
    scheduler_enabled: bool = True

    # Seuil d'échecs consécutifs avant bascule d'un compte en saisie manuelle
    manual_required_after_failures: int = 3


@lru_cache
def get_settings() -> Settings:
    return Settings()
