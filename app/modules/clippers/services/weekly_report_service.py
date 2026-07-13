"""Rapports hebdomadaires envoyés sur Discord via des webhooks.

Deux rapports, postés le dimanche 20h (après la génération du récap de 18h) :

- **Clippers** (webhook `DISCORD_REPORT_WEBHOOK_URL`) : public, sans argent —
  top 3 des clippeurs par vues générées sur la semaine (delta 7 jours) + total
  des vues générées sur le mois (delta 30 jours, tous clippeurs confondus).
- **Staff** (webhook `DISCORD_STAFF_WEBHOOK_URL`) : confidentiel — classement
  complet issu du dernier `PayoutCycle` avec vues et montants dus.

Les URL de webhook sont lues dans l'environnement (injecté par docker-compose
via `env_file`), pour ne pas avoir à modifier `config.py`.
"""

import logging
import os
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.clippers.models import Clipper
from app.modules.clippers.services import evolution_service, payout_service

logger = logging.getLogger(__name__)

GOLD = 15844367


def _fmt(n: int) -> str:
    """12345678 -> '12 345 678'."""
    return f"{int(n):,}".replace(",", " ")


def _fmt_short(n: int) -> str:
    """320000 -> '320k', 1240000 -> '1.2M'."""
    a = abs(n)
    if a >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if a >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(int(n))


def _eur(cents: int) -> str:
    """1234 -> '12,34 €'."""
    return f"{cents / 100:.2f} €".replace(".", ",")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clipper_delta(db: Session, clipper_id: int, days: int) -> tuple[int, int]:
    """(vues générées sur `days` jours, total actuel) pour un clippeur."""
    totals = evolution_service.clipper_daily_totals(db, clipper_id)  # [(date, total)]
    if not totals:
        return 0, 0
    current = totals[-1][1]
    cutoff = date.today() - timedelta(days=days)
    baseline = None
    for d, t in totals:
        if d <= cutoff:
            baseline = t
    if baseline is None:
        baseline = totals[0][1]
    return current - baseline, current


def compute_view_deltas(db: Session, days: int = 7) -> list[tuple[Clipper, int, int]]:
    """[(clipper, delta_vues, total_actuel)] trié par delta décroissant."""
    clippers = db.scalars(select(Clipper).where(Clipper.active.is_(True))).all()
    rows = [(c, *(_clipper_delta(db, c.id, days))) for c in clippers]
    rows.sort(key=lambda r: r[1], reverse=True)
    return rows


# --------------------------------------------------------------------------
# Rapport CLIPPERS (public, sans argent)
# --------------------------------------------------------------------------
def build_clipper_embed(db: Session) -> dict:
    weekly = compute_view_deltas(db, 7)
    top3 = [r for r in weekly if r[1] > 0][:3] or weekly[:3]
    medals = ["🥇", "🥈", "🥉"]
    lines = [
        f"{medals[i]} **{c.name}** — `{_fmt(delta)}` vues"
        for i, (c, delta, _current) in enumerate(top3)
    ]
    if not lines:
        lines = ["_Pas encore de données cette semaine._"]

    month_total = sum(delta for _c, delta, _cur in compute_view_deltas(db, 30))
    return {
        "title": "📊 Vues de la semaine",
        "description": "🏆 **Top 3 clippeurs de la semaine**\n\n" + "\n".join(lines),
        "color": GOLD,
        "fields": [
            {"name": "📅 Total des vues ce mois-ci", "value": f"**{_fmt(month_total)}** vues", "inline": False},
        ],
        "footer": {"text": "Bot design by systeme.one"},
        "timestamp": _now_iso(),
    }


# --------------------------------------------------------------------------
# Rapport STAFF (confidentiel, avec argent) — basé sur le dernier PayoutCycle
# --------------------------------------------------------------------------
def build_staff_embed(db: Session) -> dict:
    cycles = payout_service.list_cycles(db)
    if not cycles:
        return {
            "title": "📊 Rapport hebdomadaire — Vues & paiements (staff)",
            "description": "_Aucun récap de paiement généré pour l'instant._",
            "color": GOLD,
            "footer": {"text": "BobbyPodastOS · Rapport staff (confidentiel)"},
            "timestamp": _now_iso(),
        }

    cycle = cycles[0]
    ordered = sorted(cycle.lines, key=lambda l: l.delta_views, reverse=True)
    ranked = [l for l in ordered if l.delta_views > 0] or ordered
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    rows = [
        f"{medals.get(i, f'**{i + 1}.**')} **{line.clipper.name}** — "
        f"`{_fmt(line.delta_views)}` vues  ·  +{_fmt_short(line.delta_views)}  ·  "
        f"**{_eur(line.amount_due_cents)}**"
        for i, line in enumerate(ranked)
    ]
    total_views = sum(l.delta_views for l in cycle.lines)
    total_due = sum(l.amount_due_cents for l in cycle.lines)
    description = (
        f"**Semaine du {cycle.week_start_date.strftime('%d/%m')} "
        f"au {cycle.week_end_date.strftime('%d/%m/%Y')}**\n\n"
        "🏆 **Classement des clippeurs**\n\n"
        + ("\n".join(rows) if rows else "_Aucune vue générée cette semaine._")
        + "\n\n━━━━━━━━━━━━━━━━━━━━━━"
    )
    return {
        "title": "📊 Rapport hebdomadaire — Vues & paiements (staff)",
        "description": description,
        "color": GOLD,
        "fields": [
            {"name": "📈 Vues générées (semaine)", "value": f"**{_fmt(total_views)}**", "inline": True},
            {"name": "💶 À verser", "value": f"**{_eur(total_due)}**", "inline": True},
            {"name": "👥 Clippeurs", "value": f"**{len(cycle.lines)}**", "inline": True},
        ],
        "footer": {"text": "BobbyPodastOS · Rapport staff (confidentiel)"},
        "timestamp": _now_iso(),
    }


# --------------------------------------------------------------------------
# Envoi
# --------------------------------------------------------------------------
def _post(url: str, embed: dict, label: str) -> bool:
    if not url:
        logger.warning("Webhook %s non configuré : rapport ignoré.", label)
        return False
    try:
        resp = httpx.post(url, json={"embeds": [embed]}, timeout=15)
    except Exception as exc:
        logger.error("Erreur envoi rapport %s : %s", label, exc)
        return False
    if resp.status_code >= 300:
        logger.error("Échec rapport %s (%s) : %s", label, resp.status_code, resp.text[:300])
        return False
    logger.info("Rapport %s envoyé.", label)
    return True


def send_clipper_report(db: Session) -> bool:
    return _post(os.getenv("DISCORD_REPORT_WEBHOOK_URL", ""), build_clipper_embed(db), "clippers")


def send_staff_report(db: Session) -> bool:
    return _post(os.getenv("DISCORD_STAFF_WEBHOOK_URL", ""), build_staff_embed(db), "staff")


def send_all_reports(db: Session) -> dict:
    return {"clipper": send_clipper_report(db), "staff": send_staff_report(db)}
