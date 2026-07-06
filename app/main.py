from __future__ import annotations

import logging
import os

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app.core import scheduler
from app.core.auth import (
    SESSION_COOKIE,
    create_session_cookie,
    ensure_admin_exists,
    get_current_user,
    require_user,
    verify_password,
)
from app.core.database import get_db
from app.core.settings_service import (
    get_min_views_per_video,
    get_rate_cents,
    get_usd_eur_rate,
    set_min_views_per_video,
    set_rate_cents,
    set_usd_eur_rate,
)
from app.core.templating import templates
from app.modules.clippers.models import User
from app.modules.clippers.routers.clippers import router as clippers_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="PodcastOS — Clippers")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(clippers_router)


@app.on_event("startup")
def on_startup() -> None:
    db = next(get_db())
    try:
        ensure_admin_exists(db)
    finally:
        db.close()
    scheduler.start()


@app.on_event("shutdown")
def on_shutdown() -> None:
    scheduler.stop()


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
@limiter.limit("10/minute")
async def do_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    from app.modules.clippers.models import User as UserModel
    user = db.query(UserModel).filter_by(username=username).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Identifiants incorrects"},
            status_code=401,
        )
    response = RedirectResponse("/clippers", status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        create_session_cookie(user.id),
        httponly=True,
        samesite="lax",
        secure=os.environ.get("SECURE_COOKIES", "false").lower() == "true",
        max_age=60 * 60 * 24 * 7,
    )
    return response


@app.post("/logout")
def do_logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@app.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "user": user,
            "rate_cents": get_rate_cents(db),
            "min_views": get_min_views_per_video(db),
            "usd_eur_rate": get_usd_eur_rate(db),
        },
    )


@app.post("/settings")
def save_settings(
    request: Request,
    rate_cents: int = Form(...),
    min_views: int = Form(...),
    usd_eur_rate: float = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    if user.role != "admin":
        raise HTTPException(403)
    set_rate_cents(db, max(0, rate_cents))
    set_min_views_per_video(db, max(0, min_views))
    set_usd_eur_rate(db, max(0.01, usd_eur_rate))
    return RedirectResponse("/settings", status_code=303)


@app.get("/")
def root():
    return RedirectResponse("/clippers")
