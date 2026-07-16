"""Schémas de l'API JSON.

Convention : on écrit en snake_case côté Python et l'API sort du camelCase
(alias_generator + response_model_by_alias, actif par défaut dans FastAPI), pour
rester idiomatique des deux côtés de la frontière.

Les montants sont TOUJOURS transportés en centimes entiers, jamais en euros
flottants : 0.1 + 0.2 != 0.3 n'a pas sa place dans un calcul de paie. Le
formatage (« 195,00 € », « 412 k ») est la responsabilité de l'UI.
"""

from datetime import date

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class UserOut(ApiModel):
    id: int
    email: str
    role: str
    is_admin: bool


class SessionOut(ApiModel):
    user: UserOut | None
    csrf_token: str


class LoginIn(ApiModel):
    email: str
    password: str


class DailyPoint(ApiModel):
    date: date
    views: int
    """Vues gagnées ce jour-là (delta avec la veille), pas le cumul."""
    delta: int


class SourceBreakdown(ApiModel):
    platform: str
    label: str
    views: int
    """Part des vues du clippeur, en pourcentage (0-100)."""
    share: float
    accounts: int
    # Aucun tracking de clics n'existe à ce jour : toujours None, affiché « N/A ».
    clicks: int | None = None


class VideoOut(ApiModel):
    id: int
    title: str | None
    url: str | None
    views: int
    platform: str
    published_at: date | None
    """Série des vues de la vidéo, du plus ancien au plus récent (courbe de suivi)."""
    daily: list[int] = []


class ClipperOut(ApiModel):
    id: int
    name: str
    initials: str
    active: bool
    total_views: int
    unpaid_views: int
    amount_due_cents: int
    """Vues gagnées sur les 7 derniers jours."""
    weekly_delta_views: int
    video_count: int
    payment_method: str | None
    payment_label: str | None
    payment_handle: str | None
    daily: list[DailyPoint]
    sources: list[SourceBreakdown]
    videos: list[VideoOut]
    # --- Non mesuré à ce jour ---
    # Le modèle de rémunération cible est « vues + clics », mais aucun système de
    # tracking de liens n'existe encore. On expose donc None plutôt que 0 : un 0
    # se confondrait avec « mesuré, et nul », et fausserait toute somme.
    clicks: int | None = None
    conversion: float | None = None


class CampaignTotals(ApiModel):
    total_views: int
    gross_amount_cents: int
    unpaid_amount_cents: int
    paid_amount_cents: int
    unpaid_views: int
    accounts: int
    clippers: int


class ClippingOut(ApiModel):
    rate_cents_per_1000: int
    """False tant qu'aucun tracking de clics n'est branché : l'UI affiche « N/A »
    au lieu d'un chiffre, sur les clics comme sur la conversion."""
    clicks_tracking_enabled: bool
    totals: CampaignTotals
    clippers: list[ClipperOut]
