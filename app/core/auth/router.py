from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app.core.auth import service
from app.core.auth.csrf import verify_csrf
from app.core.auth.deps import SESSION_USER_KEY
from app.core.templating import flash, templates
from app.db import get_db

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


@router.get("/login")
def login_form(request: Request, next: str = "/"):
    if request.session.get(SESSION_USER_KEY):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"next_url": next})


@router.post("/login")
@limiter.limit("5/minute")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    user = service.authenticate(db, email, password)
    if user is None:
        flash(request, "Identifiants invalides.", "error")
        return RedirectResponse(f"/login?next={next}", status_code=303)
    request.session[SESSION_USER_KEY] = user.id
    if not next.startswith("/") or next.startswith("//"):
        next = "/"
    return RedirectResponse(next, status_code=303)


@router.post("/logout")
def logout(request: Request, _csrf: None = Depends(verify_csrf)):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
