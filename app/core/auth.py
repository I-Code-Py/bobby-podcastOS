from __future__ import annotations

import os
from functools import wraps
from typing import Any, Callable

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.clippers.models import User

ph = PasswordHasher()

_SECRET = os.environ.get("SECRET_KEY", "change-me-in-production-please")
_signer = URLSafeTimedSerializer(_SECRET)
SESSION_COOKIE = "session"
MAX_AGE = 60 * 60 * 24 * 7  # 7 days


def hash_password(password: str) -> str:
    return ph.hash(password)


def verify_password(password: str, hash_: str) -> bool:
    try:
        return ph.verify(hash_, password)
    except VerifyMismatchError:
        return False


def create_session_cookie(user_id: int) -> str:
    return _signer.dumps(user_id)


def _decode_session(token: str) -> int | None:
    try:
        return _signer.loads(token, max_age=MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def get_current_user(
    request: Request, db: Session = Depends(get_db)
) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    user_id = _decode_session(token)
    if user_id is None:
        return None
    return db.get(User, user_id)


def require_user(user: User | None = Depends(get_current_user)) -> User:
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_302_FOUND,
            headers={"Location": "/login"},
        )
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin required")
    return user


def ensure_admin_exists(db: Session) -> None:
    """Create default admin account if no users exist."""
    if db.query(User).count() == 0:
        admin = User(
            username="admin",
            password_hash=hash_password(
                os.environ.get("ADMIN_PASSWORD", "changeme123")
            ),
            role="admin",
        )
        db.add(admin)
        db.commit()
