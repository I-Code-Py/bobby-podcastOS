from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# Version applicative, affichée dans le footer. À incrémenter à chaque
# déploiement pour vérifier d'un coup d'œil quelle version tourne en prod.
APP_VERSION = "1.0.3"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./data/app.db"
    secret_key: str = "dev-secret-change-me"
    session_secure: bool = False

    youtube_api_key: str = ""
    scrape_delay_seconds: float = 5.0
    instagram_delay_seconds: float = 12.0
    # Fichier de cookies (format Netscape) exporté depuis un navigateur connecté.
    # Optionnel : fiabilise YouTube/TikTok via yt-dlp si besoin.
    cookies_file: str = ""

    # Fichier de cookies (format Netscape) d'un compte Instagram CONNECTÉ.
    # Indispensable : Instagram bloque désormais l'accès anonyme aux profils
    # depuis une IP datacenter (HTTP 429 + redirection vers /accounts/login).
    # Exporte un cookies.txt depuis un navigateur où tu es connecté à Instagram
    # (extension « Get cookies.txt ») et pointe ce réglage sur son chemin dans
    # le conteneur, ex : /srv/app/data/instagram_cookies.txt
    instagram_cookies_file: str = ""

    # Token API Apify (apify.com). Voie RECOMMANDÉE pour Instagram : l'actor
    # « apify/instagram-reel-scraper » liste les reels d'un profil avec leur
    # nombre de vues (videoPlayCount), via les proxies d'Apify — donc SANS
    # cookie et sans risque de ban d'un compte. Free tier : 5 $/mois.
    # Si renseigné, il est utilisé en priorité pour Instagram (repli cookies
    # puis saisie manuelle sinon).
    apify_token: str = ""
    # Fenêtre TEMPORELLE du scan Instagram : on récupère tous les reels postés
    # dans les N derniers jours (peu importe leur nombre), via le filtre natif
    # `onlyPostsNewerThan` de l'actor. Un clippeur prolifique n'est donc jamais
    # tronqué par un plafond de reels. Défaut : 30 jours (le mois).
    instagram_scan_days: int = 30
    # Garde-fou anti-coût : plafond dur du nombre de reels récupérés par compte
    # et par scrape (si dépassé, on loggue — pas de troncature silencieuse).
    instagram_apify_results_limit: int = 200

    timezone: str = "Europe/Paris"
    scheduler_enabled: bool = True

    # Seuil d'échecs consécutifs avant bascule d'un compte en saisie manuelle
    manual_required_after_failures: int = 3


@lru_cache
def get_settings() -> Settings:
    return Settings()
