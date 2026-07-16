"""Vue « Équipe / Rôles & permissions » du SPA.

Ce que le prototype dessinait ici ne tenait à rien : le formulaire d'invitation
n'envoyait aucune requête, les bascules de permissions écrivaient dans un tableau
JavaScript par indice, et personne ne LISAIT jamais ces permissions. Les
endpoints ci-dessous sont l'inverse : identifiants explicites, écritures
idempotentes, et un garde-fou qui refuse de fermer la porte du dernier admin.

Les schémas vivent dans ce fichier plutôt que dans `app/api/schemas.py` : ils ne
servent qu'ici et n'ont pas à peser sur le contrat partagé.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_api_user, require_api_admin, verify_csrf_header
from app.api.schemas import ApiModel
from app.core.auth.models import JOB_LABELS, JOBS, User
from app.db import get_db
from app.modules.team.models import INVITE_STATUSES, Invitation
from app.modules.team.services import invitation_service, team_service

router = APIRouter(prefix="/api/v2", tags=["team"])


# --- Schémas -----------------------------------------------------------------


class PermissionsOut(ApiModel):
    """Les deux colonnes du tableau « Rôles & permissions ». Regroupées en objet
    pour que l'UI ne devine pas quels champs plats sont des droits."""

    can_manage_photos: bool
    can_view_pay: bool


class MemberOut(ApiModel):
    id: int
    """Dérivés de `display_name` (ou de l'email en repli) : jamais stockés, donc
    jamais désynchronisés du nom."""
    name: str
    initials: str
    email: str
    job: str | None
    job_label: str | None
    role: str
    is_admin: bool
    status: str
    active: bool
    contact_channel: str | None
    permissions: PermissionsOut


class JobOut(ApiModel):
    value: str
    label: str


class MemberUpdateIn(ApiModel):
    """Tout est optionnel : un champ absent n'est pas touché. Une chaîne vide,
    elle, efface volontairement la valeur."""

    display_name: str | None = None
    job: str | None = None
    role: str | None = None
    contact_channel: str | None = None
    whatsapp_number: str | None = None
    discord_user_id: str | None = None


class PermissionsIn(ApiModel):
    """La valeur VOULUE, pas une bascule : rejouer la requête est sans effet, et
    deux clients concurrents convergent au lieu de s'annuler."""

    can_manage_photos: bool | None = None
    can_view_pay: bool | None = None


class InvitationOut(ApiModel):
    id: int
    user_id: int
    email: str
    name: str
    job: str | None
    job_label: str | None
    status: str
    channel: str | None
    expired: bool
    sent_at: datetime | None
    send_error: str | None
    expires_at: datetime
    accepted_at: datetime | None
    created_at: datetime
    """Un aperçu du jeton (8 caractères) pour rapprocher un lien reçu d'une ligne
    de la liste, sans qu'il soit rejouable. Le jeton entier n'est rendu QU'À la
    création."""
    token_preview: str


class InvitationCreatedOut(ApiModel):
    invitation: InvitationOut
    """SEUL endroit où le jeton complet sort de l'API. L'envoi automatique
    (Evolution API / Discord) n'étant pas branché, l'admin doit pouvoir composer
    le lien d'acceptation et le transmettre à la main. Une fois l'envoi branché,
    ce champ pourra disparaître sans toucher au reste du contrat."""
    token: str


class InvitationCreateIn(ApiModel):
    email: str
    display_name: str
    job: str
    channel: str | None = None
    whatsapp_number: str | None = None
    discord_user_id: str | None = None


class InvitationAcceptIn(ApiModel):
    token: str
    password: str


# --- Sérialisation -----------------------------------------------------------


def _member_out(user: User) -> MemberOut:
    # Le schéma est construit champ par champ, sans `from_attributes` : aucun
    # ajout de colonne sur `User` — `password_hash` en tête — ne peut remonter
    # jusqu'au SPA par inadvertance.
    return MemberOut(
        id=user.id,
        name=user.name,
        initials=user.initials,
        email=user.email,
        job=user.job,
        job_label=JOB_LABELS.get(user.job) if user.job else None,
        role=user.role,
        is_admin=user.is_admin,
        status=user.status,
        active=user.active,
        contact_channel=user.contact_channel,
        permissions=PermissionsOut(
            can_manage_photos=user.can_manage_photos,
            can_view_pay=user.can_view_pay,
        ),
    )


def _invitation_out(invitation: Invitation, user: User) -> InvitationOut:
    return InvitationOut(
        id=invitation.id,
        user_id=user.id,
        email=user.email,
        name=user.name,
        job=user.job,
        job_label=JOB_LABELS.get(user.job) if user.job else None,
        status=invitation.status,
        channel=invitation.channel,
        # Calculé à la lecture : une invitation n'a personne pour la faire
        # expirer d'elle-même, son statut reste « pending » à jamais en base.
        expired=invitation.is_expired,
        sent_at=invitation.sent_at,
        send_error=invitation.send_error,
        expires_at=invitation.expires_at,
        accepted_at=invitation.accepted_at,
        created_at=invitation.created_at,
        token_preview=invitation.token[:8],
    )


def _get_member_or_404(db: Session, user_id: int) -> User:
    user = team_service.get_member(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Membre introuvable")
    return user


def _guard(call):
    """Traduit les refus des services en réponses HTTP.

    Le dernier admin est un 409 et non un 400 : la requête est bien formée, c'est
    l'état du studio qui l'interdit — et le SPA doit pouvoir distinguer « corrige
    ta saisie » de « nomme d'abord un autre admin ».
    """
    try:
        return call()
    except team_service.LastAdminError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# --- Lecture -----------------------------------------------------------------


@router.get("/team", response_model=list[MemberOut])
def read_team(db: Session = Depends(get_db), _user: User = Depends(get_api_user)):
    """La liste des humains du studio. Le prototype y agrégeait « Tom, Nadia &
    Iliès » en UNE ligne porteuse de permissions : trois personnes, un seul
    interrupteur. Une ligne = une personne."""
    return [_member_out(user) for user in team_service.list_members(db)]


@router.get("/jobs", response_model=list[JobOut])
def read_jobs(_user: User = Depends(get_api_user)):
    """L'énumération fermée des métiers, servie par le serveur.

    Le prototype la recopiait en dur dans son `<select>` : la liste du formulaire
    et celle qui aurait validé les données pouvaient diverger sans que rien ne le
    signale.
    """
    return [JobOut(value=job, label=JOB_LABELS[job]) for job in JOBS]


# --- Mutations sur les membres (admin) ---------------------------------------


@router.patch("/team/members/{member_id}", response_model=MemberOut)
def update_member(
    member_id: int,
    payload: MemberUpdateIn,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_api_admin),
    _csrf: None = Depends(verify_csrf_header),
):
    user = _get_member_or_404(db, member_id)
    _guard(
        lambda: team_service.update_member(
            db,
            user,
            display_name=payload.display_name,
            job=payload.job,
            role=payload.role,
            contact_channel=payload.contact_channel,
            whatsapp_number=payload.whatsapp_number,
            discord_user_id=payload.discord_user_id,
        )
    )
    return _member_out(user)


@router.patch("/team/members/{member_id}/permissions", response_model=MemberOut)
def update_permissions(
    member_id: int,
    payload: PermissionsIn,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_api_admin),
    _csrf: None = Depends(verify_csrf_header),
):
    """Réservé aux admins — le prototype laissait n'importe qui basculer une
    permission, sans même appeler son propre `isAdmin()`."""
    user = _get_member_or_404(db, member_id)
    _guard(
        lambda: team_service.set_permissions(
            db,
            user,
            can_manage_photos=payload.can_manage_photos,
            can_view_pay=payload.can_view_pay,
        )
    )
    return _member_out(user)


@router.post("/team/members/{member_id}/deactivate", response_model=MemberOut)
def deactivate_member(
    member_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_api_admin),
    _csrf: None = Depends(verify_csrf_header),
):
    user = _get_member_or_404(db, member_id)
    _guard(lambda: team_service.deactivate_member(db, user))
    return _member_out(user)


# --- Invitations -------------------------------------------------------------


@router.post("/team/invitations", response_model=InvitationCreatedOut, status_code=201)
def create_invitation(
    payload: InvitationCreateIn,
    db: Session = Depends(get_db),
    admin: User = Depends(require_api_admin),
    _csrf: None = Depends(verify_csrf_header),
):
    invitation = _guard(
        lambda: invitation_service.create_invitation(
            db,
            email=payload.email,
            display_name=payload.display_name,
            job=payload.job,
            invited_by=admin,
            channel=payload.channel,
            whatsapp_number=payload.whatsapp_number,
            discord_user_id=payload.discord_user_id,
        )
    )
    user = _get_member_or_404(db, invitation.user_id)
    return InvitationCreatedOut(
        invitation=_invitation_out(invitation, user),
        token=invitation.token,
    )


@router.get("/team/invitations", response_model=list[InvitationOut])
def read_invitations(
    status: str | None = None,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_api_admin),
):
    if status is not None and status not in INVITE_STATUSES:
        raise HTTPException(status_code=400, detail=f"Statut d'invitation invalide : {status}")
    invitations = invitation_service.list_invitations(db, status=status)
    out: list[InvitationOut] = []
    for invitation in invitations:
        user = team_service.get_member(db, invitation.user_id)
        if user is None:
            # Compte supprimé sous l'invitation (ON DELETE CASCADE couvre le cas
            # normal) : on ne montre pas une ligne qu'on ne sait pas nommer.
            continue
        out.append(_invitation_out(invitation, user))
    return out


@router.post("/team/invitations/{invitation_id}/revoke", response_model=InvitationOut)
def revoke_invitation(
    invitation_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_api_admin),
    _csrf: None = Depends(verify_csrf_header),
):
    invitation = db.get(Invitation, invitation_id)
    if invitation is None:
        raise HTTPException(status_code=404, detail="Invitation introuvable")
    _guard(lambda: invitation_service.revoke_invitation(db, invitation))
    user = _get_member_or_404(db, invitation.user_id)
    return _invitation_out(invitation, user)


@router.post("/team/invitations/accept", response_model=MemberOut)
def accept_invitation(payload: InvitationAcceptIn, db: Session = Depends(get_db)):
    """PUBLIC, et c'est voulu : l'invité n'a pas encore de session — c'est
    précisément ce qu'il vient chercher. Exiger `get_api_user` ici rendrait
    l'invitation inutilisable par la seule personne censée s'en servir.

    Pas de `verify_csrf_header` non plus : sans session, il n'y a pas de jeton
    CSRF à comparer. Le jeton d'invitation joue ce rôle — il est secret, à usage
    unique, et un attaquant qui le possède n'a rien à gagner à le faire jouer par
    la victime.
    """
    user = _guard(lambda: invitation_service.accept_invitation(db, payload.token, payload.password))
    return _member_out(user)
