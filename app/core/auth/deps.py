from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.auth.models import User
from app.db import get_db

SESSION_USER_KEY = "user_id"


class NotAuthenticatedError(Exception):
    """Levée quand aucune session valide n'existe ; interceptée par un
    exception handler qui redirige vers /login."""

    def __init__(self, next_url: str = "/"):
        self.next_url = next_url


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.session.get(SESSION_USER_KEY)
    if user_id is not None:
        user = db.get(User, user_id)
        if user is not None and user.active:
            return user
        request.session.clear()
    raise NotAuthenticatedError(next_url=str(request.url.path))


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Accès réservé aux administrateurs")
    return user
