"""CLI d'administration : python -m app.cli <commande>"""

import typer

app = typer.Typer(help="Outils d'administration du Clip Payout Tool")


@app.command()
def init_db():
    """Crée les tables (dev uniquement — en production, utiliser alembic upgrade head)."""
    from app.db import init_db as _init_db

    _init_db()
    typer.echo("Base initialisée.")


@app.command()
def create_user(
    email: str = typer.Option(..., prompt=True),
    password: str = typer.Option(..., prompt=True, hide_input=True,
                                 confirmation_prompt=True),
    admin: bool = typer.Option(False, "--admin", help="Donner le rôle administrateur"),
):
    """Crée un utilisateur (le premier doit être un --admin)."""
    from app.core.auth import service
    from app.db import session_scope

    if len(password) < 10:
        typer.echo("Le mot de passe doit faire au moins 10 caractères.", err=True)
        raise typer.Exit(1)
    db = session_scope()
    try:
        user = service.create_user(db, email, password,
                                   "admin" if admin else "viewer")
        typer.echo(f"Utilisateur {user.email} créé (rôle {user.role}).")
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)
    finally:
        db.close()


@app.command()
def refresh_views():
    """Scrape les vues de tous les comptes actifs."""
    from app.modules.clippers.jobs import refresh_all_views

    stats = refresh_all_views()
    typer.echo(f"Terminé : {stats['ok']} ok, {stats['failed']} échec(s) "
               f"sur {stats['total']} compte(s).")


@app.command()
def weekly_payout():
    """Génère le récap hebdomadaire de paiement."""
    from app.modules.clippers.jobs import generate_weekly_payout

    cycle_id = generate_weekly_payout()
    typer.echo(f"Récap #{cycle_id} généré.")


@app.command()
def weekly_report():
    """Envoie les rapports hebdomadaires (clippers + staff) sur Discord."""
    from app.modules.clippers.jobs import send_weekly_reports

    res = send_weekly_reports()
    typer.echo(f"Clippers: {'ok' if res['clipper'] else 'échec'} | "
               f"Staff: {'ok' if res['staff'] else 'échec'}")


if __name__ == "__main__":
    app()
