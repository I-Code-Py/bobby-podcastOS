from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _build_engine():
    settings = get_settings()
    connect_args = {}
    if settings.database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Crée toutes les tables (dev/tests). En production, utiliser Alembic."""
    import app.core.auth.models  # noqa: F401
    import app.modules.clippers.models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def session_scope() -> Session:
    """Session autonome pour les jobs planifiés et la CLI (à fermer par l'appelant)."""
    return SessionLocal()
