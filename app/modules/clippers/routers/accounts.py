from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.auth.csrf import verify_csrf
from app.core.auth.deps import require_admin
from app.core.templating import flash, templates
from app.db import get_db
from app.modules.clippers.models import Account, Clipper
from app.modules.clippers.services import (
    account_service,
    clipper_service,
    view_refresh_service,
)

router = APIRouter(tags=["accounts"])


@router.post("/clippers/{clipper_id}/accounts")
def add_account(clipper_id: int, request: Request,
                url: str = Form(...),
                db: Session = Depends(get_db),
                user=Depends(require_admin),
                _csrf: None = Depends(verify_csrf)):
    clipper = clipper_service.get_clipper(db, clipper_id)
    if clipper is None:
        raise HTTPException(status_code=404)
    try:
        account = account_service.add_account(db, clipper, url)
    except ValueError as exc:
        flash(request, str(exc), "error")
        return RedirectResponse(f"/clippers/{clipper_id}", status_code=303)
    # Premier scraping immédiat pour remonter les vues tout de suite
    ok = view_refresh_service.refresh_account(db, account)
    if ok:
        flash(request, f"Compte {account.platform_label} ajouté : "
                       f"{account.latest_video_count} vidéos, "
                       f"{account.latest_total_views} vues.", "success")
    else:
        flash(request, f"Compte {account.platform_label} ajouté mais le scraping a "
                       "échoué — vous pouvez saisir le total de vues manuellement.",
              "error")
    return RedirectResponse(f"/clippers/{clipper_id}", status_code=303)


@router.post("/accounts/{account_id}/manual-views")
def set_manual_views(account_id: int, request: Request,
                     total_views: int = Form(...),
                     db: Session = Depends(get_db),
                     user=Depends(require_admin),
                     _csrf: None = Depends(verify_csrf)):
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404)
    try:
        account_service.record_manual_total(db, account, total_views)
    except ValueError as exc:
        flash(request, str(exc), "error")
    else:
        flash(request, "Total de vues enregistré manuellement.", "success")
    return RedirectResponse(f"/clippers/{account.clipper_id}", status_code=303)


@router.post("/accounts/{account_id}/refresh")
def refresh_account(account_id: int, request: Request,
                    db: Session = Depends(get_db),
                    user=Depends(require_admin),
                    _csrf: None = Depends(verify_csrf)):
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404)
    view_refresh_service.reactivate_account(db, account)
    ok = view_refresh_service.refresh_account(db, account)
    if ok:
        flash(request, f"Scraping OK : {account.latest_total_views} vues "
                       f"({account.latest_video_count} vidéos).", "success")
    else:
        flash(request, f"Le scraping échoue : {account.last_fetch_error}", "error")
    return RedirectResponse(f"/clippers/{account.clipper_id}", status_code=303)


@router.post("/accounts/{account_id}/reassign")
def reassign_account(account_id: int, request: Request,
                     new_clipper_id: int = Form(...),
                     db: Session = Depends(get_db),
                     user=Depends(require_admin),
                     _csrf: None = Depends(verify_csrf)):
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404)
    old_clipper_id = account.clipper_id
    new_clipper = db.get(Clipper, new_clipper_id)
    if new_clipper is None:
        raise HTTPException(status_code=404)
    try:
        account_service.reassign_account(db, account, new_clipper)
    except ValueError as exc:
        flash(request, str(exc), "error")
        return RedirectResponse(f"/clippers/{old_clipper_id}", status_code=303)
    flash(request, f"Compte réassigné à « {new_clipper.name} ».", "success")
    return RedirectResponse(f"/clippers/{new_clipper.id}", status_code=303)


@router.post("/accounts/{account_id}/archive")
def archive_account(account_id: int, request: Request,
                    db: Session = Depends(get_db),
                    user=Depends(require_admin),
                    _csrf: None = Depends(verify_csrf)):
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404)
    clipper_id = account.clipper_id
    account_service.archive_account(db, account)
    flash(request, "Compte archivé (retiré du suivi et des paiements).", "info")
    return RedirectResponse(f"/clippers/{clipper_id}", status_code=303)


@router.post("/accounts/{account_id}/delete")
def delete_account(account_id: int, request: Request,
                   db: Session = Depends(get_db),
                   user=Depends(require_admin),
                   _csrf: None = Depends(verify_csrf)):
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404)
    clipper_id = account.clipper_id
    try:
        account_service.delete_account(db, account)
    except ValueError as exc:
        flash(request, str(exc), "error")
    else:
        flash(request, "Compte supprimé définitivement.", "success")
    return RedirectResponse(f"/clippers/{clipper_id}", status_code=303)
