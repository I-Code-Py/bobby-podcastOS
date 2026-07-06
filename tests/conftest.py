import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("SESSION_SECURE", "false")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.core.auth.models  # noqa: F401 — enregistre les modèles
import app.modules.clippers.models  # noqa: F401
from app.db import Base, get_db


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db):
    from app.main import app

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def admin_user(db):
    from app.core.auth import service

    return service.create_user(db, "admin@test.fr", "motdepasse-solide", "admin")


@pytest.fixture()
def logged_client(client, db, admin_user):
    response = client.get("/login")
    csrf = _extract_csrf(response.text)
    client.post("/login", data={
        "email": "admin@test.fr",
        "password": "motdepasse-solide",
        "next": "/",
        "csrf_token": csrf,
    })
    return client


def _extract_csrf(html: str) -> str:
    import re

    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, "csrf_token introuvable dans la page"
    return match.group(1)


@pytest.fixture()
def extract_csrf():
    return _extract_csrf
