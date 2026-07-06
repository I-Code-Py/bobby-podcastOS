"""Génère un lien de paiement pré-rempli avec le montant dû, pour envoyer
l'argent au clippeur en un clic depuis l'app.

- PayPal   → https://paypal.me/{pseudo}/{montant}EUR
- Revolut  → https://revolut.me/{pseudo}/{montant}eur

Ces deux liens ouvrent l'app/le site de paiement avec le destinataire et le
montant déjà remplis : il ne reste qu'à confirmer.
"""

from app.modules.clippers.models import PAYMENT_PAYPAL, PAYMENT_REVOLUT

# Préfixes qu'on retire si l'utilisateur colle un lien complet au lieu du pseudo
_LINK_MARKERS = (
    "paypal.me/",
    "paypal.com/paypalme/",
    "revolut.me/",
    "revolut.com/",
)


def normalize_handle(raw: str | None) -> str:
    """Extrait le pseudo, que l'utilisateur saisisse le pseudo seul (« bobby »),
    un « @bobby », ou colle un lien complet (« https://paypal.me/bobby?x=1 »)."""
    handle = (raw or "").strip()
    if not handle:
        return ""
    lowered = handle.lower()
    for marker in _LINK_MARKERS:
        idx = lowered.find(marker)
        if idx != -1:
            handle = handle[idx + len(marker):]
            break
    # Ne garde que le premier segment, sans query string ni @ de tête
    return handle.split("?")[0].split("/")[0].strip().lstrip("@")


def _format_amount(amount_cents: int) -> str:
    """Montant en euros pour l'URL : entier si rond (« 10 »), sinon décimal
    avec un point (« 10.5 »)."""
    euros = amount_cents / 100
    return f"{euros:.2f}".rstrip("0").rstrip(".")


def build_payment_link(method: str | None, handle: str | None,
                       amount_cents: int) -> str | None:
    """URL de paiement pré-remplie avec le montant, ou None si aucun moyen de
    paiement n'est configuré ou si le montant est nul."""
    if not method or not handle or amount_cents <= 0:
        return None
    amount = _format_amount(amount_cents)
    if method == PAYMENT_PAYPAL:
        return f"https://paypal.me/{handle}/{amount}EUR"
    if method == PAYMENT_REVOLUT:
        return f"https://revolut.me/{handle}/{amount}eur"
    return None
