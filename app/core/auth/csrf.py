import hmac
import secrets

from fastapi import HTTPException, Request

CSRF_SESSION_KEY = "csrf_token"
CSRF_FORM_FIELD = "csrf_token"


def get_csrf_token(request: Request) -> str:
    token = request.session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[CSRF_SESSION_KEY] = token
    return token


async def verify_csrf(request: Request) -> None:
    """Dépendance à placer sur toute route POST : compare le token du
    formulaire avec celui de la session."""
    expected = request.session.get(CSRF_SESSION_KEY)
    form = await request.form()
    submitted = form.get(CSRF_FORM_FIELD)
    if not expected or not submitted or not hmac.compare_digest(str(submitted), expected):
        raise HTTPException(status_code=403, detail="Jeton CSRF invalide ou manquant")
