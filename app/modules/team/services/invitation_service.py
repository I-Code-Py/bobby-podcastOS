"""Inviter quelqu'un, et savoir s'il est vraiment arrivé.

Le prototype affichait « Invitation envoyée — en attente » sans avoir rien
envoyé, et son formulaire ne demandait que le NOM : l'invité était injoignable,
et aucun chemin n'existait pour faire passer la pastille à « accepté ». Ici une
invitation est une ligne en base avec un jeton, une expiration et un statut que
l'acceptation fait bouger pour de bon.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth.models import (
    CHANNELS,
    JOBS,
    MEMBER_ACTIVE,
    MEMBER_INVITED,
    ROLE_VIEWER,
    User,
)
from app.core.auth.security import hash_password
from app.core.auth.service import get_user_by_email
from app.modules.team.models import (
    INVITE_ACCEPTED,
    INVITE_PENDING,
    INVITE_REVOKED,
    INVITE_STATUSES,
    Invitation,
)

# Même plancher que `python -m app.cli create-user` : deux portes vers le même
# compte ne peuvent pas avoir deux exigences différentes.
MIN_PASSWORD_LENGTH = 10


def create_invitation(
    db: Session,
    email: str,
    display_name: str,
    job: str,
    invited_by: User | None = None,
    channel: str | None = None,
    whatsapp_number: str | None = None,
    discord_user_id: str | None = None,
) -> Invitation:
    """Crée le compte en attente ET son invitation, dans la même transaction.

    Le compte existe dès l'invitation (statut `invited`, sans mot de passe) pour
    que les affectations puissent le viser avant même qu'il se connecte —
    `authenticate` refuse déjà les comptes sans hash, donc ce compte muet n'est
    pas une porte ouverte.

    Les permissions naissent FERMÉES : c'est le seul point sur lequel le
    prototype avait raison. On n'invite pas quelqu'un en lui donnant d'emblée la
    vue sur la paie.
    """
    email = (email or "").strip().lower()
    if not email:
        raise ValueError("L'email est obligatoire")
    display_name = (display_name or "").strip()
    if not display_name:
        raise ValueError("Le nom est obligatoire")
    if job not in JOBS:
        raise ValueError(f"Métier invalide : {job}")
    if channel is not None and channel not in CHANNELS:
        raise ValueError(f"Canal de contact invalide : {channel}")
    if get_user_by_email(db, email) is not None:
        raise ValueError(f"Un utilisateur existe déjà avec l'email {email}")

    user = User(
        email=email,
        password_hash=None,
        role=ROLE_VIEWER,
        display_name=display_name,
        job=job,
        status=MEMBER_INVITED,
        contact_channel=channel,
        whatsapp_number=(whatsapp_number or "").strip() or None,
        discord_user_id=(discord_user_id or "").strip() or None,
        can_manage_photos=False,
        can_view_pay=False,
    )
    db.add(user)
    db.flush()

    invitation = Invitation(
        user_id=user.id,
        channel=channel,
        invited_by_id=invited_by.id if invited_by else None,
    )
    db.add(invitation)
    db.commit()
    db.refresh(invitation)
    return invitation


def accept_invitation(db: Session, token: str, password: str) -> User:
    """Échange un jeton contre un compte utilisable.

    Le jeton est à USAGE UNIQUE : l'invitation passe à `accepted`, donc
    `is_usable` devient faux et un second appel avec le même lien est refusé.
    Sans cela, un lien qui traîne dans un historique de conversation resterait
    une porte d'entrée indéfiniment.
    """
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"Le mot de passe doit faire au moins {MIN_PASSWORD_LENGTH} caractères."
        )

    invitation = db.scalar(select(Invitation).where(Invitation.token == token))
    # Message identique pour un jeton inconnu, révoqué ou expiré : le distinguer
    # renseignerait un inconnu sur ce qui existe en base.
    if invitation is None or not invitation.is_usable:
        raise ValueError("Invitation invalide ou expirée.")

    user = db.get(User, invitation.user_id)
    if user is None:
        raise ValueError("Invitation invalide ou expirée.")

    user.password_hash = hash_password(password)
    user.status = MEMBER_ACTIVE
    user.active = True
    invitation.status = INVITE_ACCEPTED
    invitation.accepted_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    return user


def revoke_invitation(db: Session, invitation: Invitation) -> Invitation:
    """Annule une invitation encore en attente.

    Le compte `invited` reste en base : il n'a pas de mot de passe, donc il ne
    connecte personne, et le supprimer casserait les affectations déjà faites
    dessus. Le retirer vraiment, c'est `team_service.deactivate_member`.
    """
    if invitation.status != INVITE_PENDING:
        raise ValueError("Seule une invitation en attente peut être révoquée.")
    invitation.status = INVITE_REVOKED
    db.commit()
    db.refresh(invitation)
    return invitation


def list_invitations(db: Session, status: str | None = None) -> list[Invitation]:
    if status is not None and status not in INVITE_STATUSES:
        raise ValueError(f"Statut d'invitation invalide : {status}")
    stmt = select(Invitation).order_by(Invitation.created_at.desc(), Invitation.id.desc())
    if status is not None:
        stmt = stmt.where(Invitation.status == status)
    return list(db.scalars(stmt))


def mark_sent(
    db: Session,
    invitation: Invitation,
    channel: str,
    error: str | None = None,
) -> Invitation:
    """Consigne la tentative d'envoi — le succès comme l'échec.

    L'ENVOI RÉEL N'EST PAS BRANCHÉ ICI : le message WhatsApp (via Evolution API,
    déjà utilisée par `clippers/services/evolution_service`) et le message privé
    Discord sont un autre chantier. Cette fonction est le point d'accroche prévu
    pour lui : il l'appellera avec `error=None` s'il aboutit, avec le motif sinon.

    Une invitation dont l'envoi a échoué reste en attente et donc relançable —
    un numéro faux se corrige, il ne se devine pas. En attendant le branchement,
    l'admin transmet le lien à la main (le jeton n'est rendu qu'à la création).
    """
    if channel not in CHANNELS:
        raise ValueError(f"Canal de contact invalide : {channel}")
    invitation.channel = channel
    invitation.sent_at = datetime.now(timezone.utc)
    invitation.send_error = error
    db.commit()
    db.refresh(invitation)
    return invitation
