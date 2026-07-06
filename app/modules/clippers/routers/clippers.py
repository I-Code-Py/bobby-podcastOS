from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.auth import require_admin, require_user
from app.core.database import get_db
from app.core.settings_service import get_usd_eur_rate
from app.core.templating import templates
from app.modules.clippers.models import (
    Account,
    AccountStatus,
    Clipper,
    PayoutCycle,
    PayoutLine,
    User,
)
from app.modules.clippers.services import (
    account_service,
    evolution_service,
    payout_service,
    view_refresh_service,
)

router = APIRouter(prefix="/clippers", tags=["clippers"])


# ---------------------------------------------------------------------------
# Clipper CRUD
# ---------------------------------------------------------------------------

@router.get("")
def list_clippers(request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    clippers = db.query(Clipper).order_by(Clipper.name).all()
    return templates.TemplateResponse(
        "clippers/index.html",
        {"request": request, "clippers": clippers, "user": user},
    )


@router.post("")
def create_clipper(
    request: Request,
    name: str = Form(...),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    clipper = Clipper(name=name.strip(), notes=notes.strip() or None)
    db.add(clipper)
    db.commit()
    return RedirectResponse(f"/clippers/{clipper.id}", status_code=303)


@router.get("/{clipper_id}")
def clipper_detail(
    clipper_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    clipper = db.get(Clipper, clipper_id)
    if not clipper:
        raise HTTPException(404, "Clipper introuvable")
    return templates.TemplateResponse(
        "clippers/detail.html",
        {"request": request, "clipper": clipper, "user": user,
         "AccountStatus": AccountStatus},
    )


@router.post("/{clipper_id}/edit")
def edit_clipper(
    clipper_id: int,
    name: str = Form(...),
    notes: str = Form(""),
    payment_link: str = Form(""),
    active: bool = Form(False),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    clipper = db.get(Clipper, clipper_id)
    if not clipper:
        raise HTTPException(404)
    clipper.name = name.strip()
    clipper.notes = notes.strip() or None
    clipper.payment_link = payment_link.strip() or None
    clipper.active = active
    db.commit()
    return RedirectResponse(f"/clippers/{clipper_id}", status_code=303)


@router.post("/{clipper_id}/delete")
def delete_clipper(
    clipper_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    clipper = db.get(Clipper, clipper_id)
    if clipper:
        db.delete(clipper)
        db.commit()
    return RedirectResponse("/clippers", status_code=303)


# ---------------------------------------------------------------------------
# Account management
# ---------------------------------------------------------------------------

@router.post("/{clipper_id}/accounts")
def add_account(
    clipper_id: int,
    profile_url: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    try:
        account_service.create_account(db, clipper_id, profile_url.strip())
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return RedirectResponse(f"/clippers/{clipper_id}", status_code=303)


@router.post("/{clipper_id}/accounts/{account_id}/delete")
def delete_account(
    clipper_id: int,
    account_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    account_service.delete_account(db, account_id)
    return RedirectResponse(f"/clippers/{clipper_id}", status_code=303)


@router.post("/{clipper_id}/accounts/{account_id}/refresh")
def refresh_one_account(
    clipper_id: int,
    account_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(404)
    try:
        view_refresh_service.refresh_account(db, account)
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return RedirectResponse(f"/clippers/{clipper_id}", status_code=303)


# ---------------------------------------------------------------------------
# Refresh all
# ---------------------------------------------------------------------------

@router.post("/refresh-all")
def refresh_all(
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    view_refresh_service.refresh_all(db)
    return RedirectResponse("/clippers", status_code=303)


# ---------------------------------------------------------------------------
# Evolution
# ---------------------------------------------------------------------------

@router.get("/{clipper_id}/evolution")
def clipper_evolution(
    clipper_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    clipper = db.get(Clipper, clipper_id)
    if not clipper:
        raise HTTPException(404)

    clipper_series = evolution_service.clipper_daily_totals(db, clipper_id)
    clipper_dates = [str(d) for d, _ in clipper_series]
    clipper_values = [v for _, v in clipper_series]

    accounts_data = []
    for account in clipper.accounts:
        series = evolution_service.account_daily_totals(db, account.id)
        acc_values = [v for _, v in series]
        acc_dates = [str(d) for d, _ in series]
        vids = evolution_service.video_histories(db, account.id)
        accounts_data.append({
            "account": account,
            "values": acc_values,
            "dates": acc_dates,
            "videos": vids,
        })

    return templates.TemplateResponse(
        "clippers/evolution.html",
        {
            "request": request,
            "clipper": clipper,
            "clipper_values": clipper_values,
            "clipper_dates": clipper_dates,
            "accounts": accounts_data,
            "user": user,
        },
    )


# ---------------------------------------------------------------------------
# Payouts
# ---------------------------------------------------------------------------

@router.get("/payouts")
def list_payouts(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    cycles = (
        db.query(PayoutCycle)
        .order_by(PayoutCycle.created_at.desc())
        .limit(20)
        .all()
    )
    usd_eur = get_usd_eur_rate(db)
    return templates.TemplateResponse(
        "clippers/payout.html",
        {"request": request, "cycles": cycles, "user": user, "usd_eur": usd_eur},
    )


@router.post("/payouts/generate")
def generate_payout(
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    payout_service.generate_cycle(db)
    return RedirectResponse("/clippers/payouts", status_code=303)


@router.post("/payouts/lines/{line_id}/pay")
def mark_line_paid(
    line_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    line = db.get(PayoutLine, line_id)
    if not line:
        raise HTTPException(404)
    if line.held:
        line.held = False
        line.hold_note = None
    payout_service.mark_paid(db, line)
    return RedirectResponse("/clippers/payouts", status_code=303)


@router.post("/payouts/lines/{line_id}/hold")
def hold_line(
    line_id: int,
    note: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    line = db.get(PayoutLine, line_id)
    if not line:
        raise HTTPException(404)
    if line.paid_at:
        raise HTTPException(400, "Ligne déjà payée")
    line.held = True
    line.hold_note = note.strip() or None
    db.commit()
    return RedirectResponse("/clippers/payouts", status_code=303)


@router.post("/payouts/lines/{line_id}/release")
def release_hold(
    line_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    line = db.get(PayoutLine, line_id)
    if not line:
        raise HTTPException(404)
    line.held = False
    line.hold_note = None
    db.commit()
    return RedirectResponse("/clippers/payouts", status_code=303)
