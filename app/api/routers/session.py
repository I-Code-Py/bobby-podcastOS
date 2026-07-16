"""Authentification du SPA.

Réutilise telle quelle la session cookie de l'UI Jinja : se connecter ici
connecte aussi l'UI v1, et inversement. Pendant la transition v1 → v2, les deux
interfaces cohabitent donc sur une seule et même session.
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_api_user_optional, verify_csrf_header
from app.api.schemas import LoginIn, SessionOut, UserOut
from app.core.auth import service
from app.core.auth.csrf import get_csrf_token
from app.core.auth.deps import SESSION_USER_KEY
from app.core.auth.models import User
from app.db import get_db

router = APIRouter(prefix="/api/v2", tags=["session"])


def _session_payload(request: Request, user: User | None) -> SessionOut:
    return SessionOut(
        user=UserOut.model_validate(user, from_attributes=True) if user else None,
        # Toujours émis, y compris déconnecté : le SPA en a besoin pour POSTer
        # /login lui-même.
        csrf_token=get_csrf_token(request),
    )


@router.get("/session", response_model=SessionOut)
def read_session(request: Request, user: User | None = Depends(get_api_user_optional)):
    """Point d'entrée du SPA au démarrage : qui suis-je, et quel est mon jeton CSRF."""
    return _session_payload(request, user)


@router.post("/login", response_model=SessionOut)
def login(
    request: Request,
    payload: LoginIn,
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf_header),
):
    from fastapi import HTTPException

    user = service.authenticate(db, payload.email, payload.password)
    if user is None:
        # Message volontairement identique pour un email inconnu et un mot de
        # passe faux : ne pas révéler quels comptes existent.
        raise HTTPException(status_code=401, detail="Identifiants invalides.")
    request.session[SESSION_USER_KEY] = user.id
    return _session_payload(request, user)


@router.post("/logout", response_model=SessionOut)
def logout(request: Request, _csrf: None = Depends(verify_csrf_header)):
    request.session.clear()
    return _session_payload(request, None)
