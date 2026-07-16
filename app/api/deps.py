"""Dépendances de l'API JSON consommée par le SPA.

L'UI Jinja et l'API partagent la même session (cookie `bobby_session`) mais pas
la même façon d'échouer :

  - l'UI redirige vers /login (303), ce qu'un `fetch()` suivrait silencieusement
    pour finir par parser du HTML en croyant lire du JSON ;
  - l'API répond 401, laissant le SPA afficher son propre écran de connexion.

D'où ces dépendances parallèles à celles de `app.core.auth.deps`.
"""

import hmac

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.auth.csrf import CSRF_SESSION_KEY
from app.core.auth.deps import SESSION_USER_KEY
from app.core.auth.models import User
from app.db import get_db

CSRF_HEADER = "X-CSRF-Token"


def get_api_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.session.get(SESSION_USER_KEY)
    if user_id is not None:
        user = db.get(User, user_id)
        if user is not None and user.active:
            return user
        request.session.clear()
    raise HTTPException(status_code=401, detail="Non authentifié")


def get_api_user_optional(request: Request, db: Session = Depends(get_db)) -> User | None:
    """Pour /session : renvoie l'utilisateur courant ou None, sans lever 401."""
    user_id = request.session.get(SESSION_USER_KEY)
    if user_id is None:
        return None
    user = db.get(User, user_id)
    if user is not None and user.active:
        return user
    request.session.clear()
    return None


def require_api_admin(user: User = Depends(get_api_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Accès réservé aux administrateurs")
    return user


def verify_csrf_header(request: Request) -> None:
    """CSRF pour l'API : le jeton voyage dans un en-tête et non dans un champ de
    formulaire.

    Un formulaire malveillant hébergé sur un autre site peut poster vers nous
    (le cookie est SameSite=Lax, donc envoyé sur une navigation POST top-level),
    mais il ne peut PAS poser d'en-tête custom sans passer par un preflight CORS
    — que nous n'autorisons pas. L'en-tête est donc la garantie que l'appel vient
    bien de notre propre origine.
    """
    expected = request.session.get(CSRF_SESSION_KEY)
    submitted = request.headers.get(CSRF_HEADER)
    if not expected or not submitted or not hmac.compare_digest(str(submitted), expected):
        raise HTTPException(status_code=403, detail="Jeton CSRF invalide ou manquant")
