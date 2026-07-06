from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.auth.csrf import verify_csrf
from app.core.auth.deps import get_current_user, require_admin
from app.core.templating import flash, templates
from app.db import get_db
from app.modules.clippers.services import (
    clipper_service,
    evolution_service,
    payout_service,
)

router = APIRouter(prefix="/clippers", tags=["clippers"])


@router.get("")
def list_clippers(request: Request, db: Session = Depends(get_db),
                  user=Depends(get_current_user)):
    clippers = clipper_service.list_clippers(db)
    rows = []
    for clipper in clippers:
        unpaid_views, unpaid_cents = payout_service.live_unpaid_estimate_cents(db, clipper)
        rows.append({
            "clipper": clipper,
            "total_views": clipper_service.total_views(clipper),
            "account_count": len(clipper_service.active_accounts(clipper)),
            "unpaid_views": unpaid_views,
            "unpaid_cents": unpaid_cents,
        })
    return templates.TemplateResponse(request, "clippers/list.html",
                                      {"rows": rows, "user": user})


@router.post("")
def create_clipper(request: Request,
                   name: str = Form(...),
                   notes: str = Form(""),
                   db: Session = Depends(get_db),
                   user=Depends(require_admin),
                   _csrf: None = Depends(verify_csrf)):
    try:
        clipper = clipper_service.create_clipper(db, name, notes=notes.strip())
    except ValueError as exc:
        flash(request, str(exc), "error")
        return RedirectResponse("/clippers", status_code=303)
    flash(request, f"Clippeur « {clipper.name} » créé.", "success")
    return RedirectResponse(f"/clippers/{clipper.id}", status_code=303)


@router.get("/{clipper_id}")
def clipper_detail(clipper_id: int, request: Request, db: Session = Depends(get_db),
                   user=Depends(get_current_user)):
    from app.core.settings_service import get_min_views_per_video

    clipper = clipper_service.get_clipper(db, clipper_id)
    if clipper is None:
        raise HTTPException(status_code=404)
    unpaid_views, unpaid_cents = payout_service.live_unpaid_estimate_cents(db, clipper)
    accounts = clipper_service.active_accounts(clipper)
    other_clippers = [c for c in clipper_service.list_clipper_names(db) if c.id != clipper_id]
    return templates.TemplateResponse(request, "clippers/detail.html", {
        "clipper": clipper,
        "accounts": accounts,
        "total_views": clipper_service.total_views(clipper),
        "unpaid_views": unpaid_views,
        "unpaid_cents": unpaid_cents,
        "min_views": get_min_views_per_video(db),
        "other_clippers": other_clippers,
        "user": user,
    })


@router.post("/{clipper_id}/delete")
def delete_clipper(clipper_id: int, request: Request, db: Session = Depends(get_db),
                   user=Depends(require_admin), _csrf: None = Depends(verify_csrf)):
    clipper = clipper_service.get_clipper(db, clipper_id)
    if clipper is None:
        raise HTTPException(status_code=404)
    name = clipper.name
    try:
        clipper_service.delete_clipper(db, clipper)
    except ValueError as exc:
        flash(request, str(exc), "error")
        return RedirectResponse(f"/clippers/{clipper_id}", status_code=303)
    flash(request, f"Clippeur « {name} » supprimé définitivement.", "success")
    return RedirectResponse("/clippers", status_code=303)


@router.post("/{clipper_id}/payment")
def set_payment(clipper_id: int, request: Request,
                method: str = Form(""),
                handle: str = Form(""),
                db: Session = Depends(get_db),
                user=Depends(require_admin),
                _csrf: None = Depends(verify_csrf)):
    clipper = clipper_service.get_clipper(db, clipper_id)
    if clipper is None:
        raise HTTPException(status_code=404)
    try:
        clipper_service.set_payment_info(db, clipper, method, handle)
    except ValueError as exc:
        flash(request, str(exc), "error")
        return RedirectResponse(f"/clippers/{clipper_id}", status_code=303)
    if clipper.payment_method:
        flash(request, f"Moyen de paiement enregistré : "
                       f"{clipper.payment_method_label} — {clipper.payment_handle}.",
              "success")
    else:
        flash(request, "Moyen de paiement retiré.", "success")
    return RedirectResponse(f"/clippers/{clipper_id}", status_code=303)


@router.get("/{clipper_id}/evolution")
def clipper_evolution(clipper_id: int, request: Request,
                      db: Session = Depends(get_db),
                      user=Depends(get_current_user)):
    clipper = clipper_service.get_clipper(db, clipper_id)
    if clipper is None:
        raise HTTPException(status_code=404)
    clipper_series = evolution_service.clipper_daily_totals(db, clipper_id)
    accounts = []
    for account in clipper_service.active_accounts(clipper):
        series = evolution_service.account_daily_totals(db, account.id)
        accounts.append({
            "account": account,
            "series": series,
            "values": [v for _, v in series],
            "videos": evolution_service.video_histories(db, account.id),
        })
    return templates.TemplateResponse(request, "clippers/evolution.html", {
        "clipper": clipper,
        "clipper_series": clipper_series,
        "clipper_values": [v for _, v in clipper_series],
        "accounts": accounts,
        "user": user,
    })
