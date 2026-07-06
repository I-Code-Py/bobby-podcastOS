from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth.models import ROLES, User
from app.core.auth.security import hash_password, verify_password


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email.strip().lower()))


def create_user(db: Session, email: str, password: str, role: str) -> User:
    if role not in ROLES:
        raise ValueError(f"Rôle invalide : {role}")
    email = email.strip().lower()
    if get_user_by_email(db, email):
        raise ValueError(f"Un utilisateur existe déjà avec l'email {email}")
    user = User(email=email, password_hash=hash_password(password), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = get_user_by_email(db, email)
    if user is None or not user.active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def list_users(db: Session) -> list[User]:
    return list(db.scalars(select(User).order_by(User.email)))


def set_user_active(db: Session, user_id: int, active: bool) -> None:
    user = db.get(User, user_id)
    if user:
        user.active = active
        db.commit()
