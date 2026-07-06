"""Scraping des vidéos d'un profil Instagram via un navigateur headless.

Instagram bloque le listing anonyme des posts d'un profil via son API/GraphQL
(yt-dlp échoue systématiquement avec "login required"). En revanche, la page
publique du profil est bien accessible sans compte dans un vrai navigateur :
on charge la page, on scrolle pour déclencher le chargement des posts
suivants (comme un visiteur normal), puis on lit les vues affichées sur
chaque vignette de reel directement dans le DOM rendu.

Fragile par nature (dépend de la structure HTML d'Instagram, qui change
régulièrement) : capturé par ConnectorError/ParsingError, avec repli en
saisie manuelle dans l'UI comme les autres connecteurs.
"""

import re

from app.modules.clippers.connectors.base import VideoInfo
from app.modules.clippers.connectors.errors import (
    ConnectorError,
    NotFoundError,
    ParsingError,
)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_MAX_SCROLLS = 15
_MAX_STALE_SCROLLS = 3  # arrête si aucun nouveau post après N scrolls d'affilée
_SCROLL_PAUSE_MS = 1500

_COUNT_RE = re.compile(r"^([\d.,]+)\s*([KMB]?)$", re.IGNORECASE)
_SHORTCODE_RE = re.compile(r"/(reel|p)/([\w-]+)")

_SUFFIX_MULTIPLIER = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}


def _parse_count(text: str) -> int | None:
    """Convertit "12,3 K", "1.2M", "834" en entier. None si non reconnu."""
    text = text.strip()
    match = _COUNT_RE.match(text)
    if not match:
        return None
    number_part, suffix = match.groups()
    if suffix:
        # Avec suffixe (K/M/B), la virgule est un séparateur décimal : "12,3 K"
        number_part = number_part.replace(",", ".")
    else:
        # Sans suffixe, la virgule est un séparateur de milliers : "12,345"
        number_part = number_part.replace(",", "")
    try:
        value = float(number_part)
    except ValueError:
        return None
    return int(value * _SUFFIX_MULTIPLIER.get(suffix.upper(), 1))


def _dismiss_overlays(page) -> None:
    """Ferme le bandeau cookies et l'éventuelle pop-up "Connectez-vous"."""
    for selector in [
        "button:has-text('Allow all cookies')",
        "button:has-text('Autoriser les cookies')",
        "button:has-text('Accept all')",
        "button:has-text('Tout accepter')",
    ]:
        try:
            page.locator(selector).first.click(timeout=2000)
        except Exception:  # noqa: BLE001 — bandeau absent, on continue
            pass
    try:
        page.keyboard.press("Escape")  # ferme une éventuelle modale de login
    except Exception:  # noqa: BLE001
        pass


def _extract_posts(page) -> dict[str, dict]:
    """Lit dans le DOM rendu chaque lien de post + le compteur de vues
    affiché sur sa vignette (uniquement présent pour les vidéos/reels)."""
    posts: dict[str, dict] = {}
    anchors = page.locator("main a[href*='/reel/'], main a[href*='/p/']")
    count = anchors.count()
    for i in range(count):
        anchor = anchors.nth(i)
        href = anchor.get_attribute("href") or ""
        match = _SHORTCODE_RE.search(href)
        if not match:
            continue
        shortcode = match.group(2)
        if shortcode in posts:
            continue
        view_count = None
        try:
            texts = anchor.locator("span").all_inner_texts()
        except Exception:  # noqa: BLE001
            texts = []
        for text in texts:
            parsed = _parse_count(text)
            if parsed is not None:
                view_count = parsed
                break
        posts[shortcode] = {
            "url": f"https://www.instagram.com/reel/{shortcode}/",
            "view_count": view_count,
        }
    return posts


def fetch_instagram_profile_videos(profile_url: str) -> list[VideoInfo]:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover
        raise ConnectorError("playwright n'est pas installé") from exc

    try:
        with sync_playwright() as pw:
            # --disable-dev-shm-usage : évite un crash de Chromium quand le
            # conteneur a peu de mémoire partagée (/dev/shm), courant sur un
            # VPS mutualisé plutôt que d'augmenter shm_size côté docker-compose.
            browser = pw.chromium.launch(
                headless=True, args=["--disable-dev-shm-usage"]
            )
            try:
                page = browser.new_page(user_agent=_USER_AGENT,
                                        viewport={"width": 1280, "height": 1600})
                response = page.goto(profile_url, wait_until="domcontentloaded",
                                     timeout=30_000)
                if response is not None and response.status == 404:
                    raise NotFoundError(f"Profil Instagram introuvable : {profile_url}")
                _dismiss_overlays(page)
                page.wait_for_timeout(1500)

                posts: dict[str, dict] = {}
                stale_rounds = 0
                for _ in range(_MAX_SCROLLS):
                    before = len(posts)
                    posts.update(_extract_posts(page))
                    if len(posts) == before:
                        stale_rounds += 1
                        if stale_rounds >= _MAX_STALE_SCROLLS:
                            break
                    else:
                        stale_rounds = 0
                    page.mouse.wheel(0, 2500)
                    page.wait_for_timeout(_SCROLL_PAUSE_MS)
                posts.update(_extract_posts(page))
            finally:
                browser.close()
    except NotFoundError:
        raise
    except PlaywrightError as exc:
        raise ConnectorError(f"Navigateur headless : {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise ConnectorError(str(exc)) from exc

    if not posts:
        raise ParsingError(
            "Aucun post trouvé sur la page — structure Instagram changée, "
            "profil privé, ou blocage temporaire"
        )

    return [
        VideoInfo(platform_video_id=shortcode, url=data["url"],
                 view_count=data["view_count"])
        for shortcode, data in posts.items()
    ]
