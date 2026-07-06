from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core import scheduler as core_scheduler
from app.core import settings_service
from app.core.auth import service as auth_service
from app.core.auth.csrf import verify_csrf
from app.core.auth.deps import get_current_user, require_admin
from app.core.templating import flash, templates
from app.db import get_db
from app.modules.clippers import jobs

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("")
def settings_page(request: Request, db: Session = Depends(get_db),
                  user=Depends(get_current_user)):
    rate_cents = settings_service.get_rate_cents(db)
    min_views = settings_service.get_min_views_per_video(db)
    users = auth_service.list_users(db) if user.is_admin else []
    return templates.TemplateResponse(request, "settings/index.html", {
        "rate_cents": rate_cents,
        "min_views": min_views,
        "users": users,
        "user": user,
    })


@router.post("/rate")
def update_rate(request: Request, rate_euros: float = Form(...),
                db: Session = Depends(get_db),
                user=Depends(require_admin), _csrf: None = Depends(verify_csrf)):
    try:
        settings_service.set_rate_cents(db, round(rate_euros * 100))
    except ValueError as exc:
        flash(request, str(exc), "error")
    else:
        flash(request, "Taux mis à jour.", "success")
    return RedirectResponse("/settings", status_code=303)


@router.post("/min-views")
def update_min_views(request: Request, min_views: int = Form(...),
                     db: Session = Depends(get_db),
                     user=Depends(require_admin), _csrf: None = Depends(verify_csrf)):
    try:
        settings_service.set_min_views_per_video(db, min_views)
    except ValueError as exc:
        flash(request, str(exc), "error")
    else:
        flash(request, "Seuil mis à jour. Il s'appliquera aux prochains scrapings.",
              "success")
    return RedirectResponse("/settings", status_code=303)


@router.post("/refresh-now")
def refresh_now(request: Request, user=Depends(require_admin),
                _csrf: None = Depends(verify_csrf)):
    if core_scheduler.run_in_background(jobs.refresh_all_views,
                                        job_id="manual-refresh"):
        flash(request, "Rafraîchissement des vues lancé en arrière-plan "
                       "(quelques minutes selon le nombre de publications).", "info")
    else:
        stats = jobs.refresh_all_views()
        flash(request, f"Rafraîchissement terminé : {stats['ok']} ok, "
                       f"{stats['failed']} échec(s).", "info")
    return RedirectResponse("/settings", status_code=303)


@router.post("/payout-now")
def payout_now(request: Request, user=Depends(require_admin),
               _csrf: None = Depends(verify_csrf)):
    cycle_id = jobs.generate_weekly_payout()
    flash(request, f"Récap #{cycle_id} généré.", "success")
    return RedirectResponse(f"/payouts/{cycle_id}", status_code=303)


@router.post("/users")
def create_user(request: Request, email: str = Form(...),
                password: str = Form(...), role: str = Form("viewer"),
                db: Session = Depends(get_db),
                user=Depends(require_admin), _csrf: None = Depends(verify_csrf)):
    if len(password) < 10:
        flash(request, "Le mot de passe doit faire au moins 10 caractères.", "error")
        return RedirectResponse("/settings", status_code=303)
    try:
        auth_service.create_user(db, email, password, role)
    except ValueError as exc:
        flash(request, str(exc), "error")
    else:
        flash(request, f"Utilisateur {email} créé.", "success")
    return RedirectResponse("/settings", status_code=303)
