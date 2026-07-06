from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.auth.csrf import verify_csrf
from app.core.auth.deps import get_current_user, require_admin
from app.core.templating import flash, templates
from app.db import get_db
from app.modules.clippers.models import PayoutCycle, PayoutLine
from app.modules.clippers.services import payout_service

router = APIRouter(prefix="/payouts", tags=["payouts"])


@router.get("")
def list_cycles(request: Request, db: Session = Depends(get_db),
                user=Depends(get_current_user)):
    cycles = payout_service.list_cycles(db)
    return templates.TemplateResponse(request, "payouts/list.html",
                                      {"cycles": cycles, "user": user})


@router.post("/generate")
def generate_now(request: Request, db: Session = Depends(get_db),
                 user=Depends(require_admin), _csrf: None = Depends(verify_csrf)):
    cycle = payout_service.generate_cycle(db)
    flash(request, f"Récap #{cycle.id} généré.", "success")
    return RedirectResponse(f"/payouts/{cycle.id}", status_code=303)


@router.get("/{cycle_id}")
def cycle_detail(cycle_id: int, request: Request, db: Session = Depends(get_db),
                 user=Depends(get_current_user)):
    cycle = db.get(PayoutCycle, cycle_id)
    if cycle is None:
        raise HTTPException(status_code=404)
    lines = sorted(cycle.lines, key=lambda line: line.amount_due_cents, reverse=True)
    total_cents = sum(line.amount_due_cents for line in lines
                      if line.status != "superseded")
    return templates.TemplateResponse(request, "payouts/detail.html", {
        "cycle": cycle,
        "lines": lines,
        "total_cents": total_cents,
        "user": user,
    })


@router.post("/lines/{line_id}/mark-paid")
def mark_paid(line_id: int, request: Request, db: Session = Depends(get_db),
              user=Depends(require_admin), _csrf: None = Depends(verify_csrf)):
    line = db.get(PayoutLine, line_id)
    if line is None:
        raise HTTPException(status_code=404)
    try:
        payout_service.mark_paid(db, line)
    except ValueError as exc:
        flash(request, str(exc), "error")
    else:
        flash(request, f"Paiement de {line.clipper.name} enregistré : les vues "
                       "correspondantes ne seront plus comptées.", "success")
    return RedirectResponse(f"/payouts/{line.payout_cycle_id}", status_code=303)
