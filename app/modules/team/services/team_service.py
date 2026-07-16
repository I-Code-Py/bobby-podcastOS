"""Les membres du studio : leur fiche, leurs droits, leur sortie.

Le prototype tenait ces informations dans un tableau JavaScript et les modifiait
PAR INDICE (`togglePhotos(i)`) : sans identifiant, deux onglets ouverts sur la
même page écrivaient l'un sur l'autre dès qu'une ligne changeait d'ordre. Ici
tout passe par l'id, et les permissions se POSENT à une valeur voulue au lieu de
basculer — un toggle perd la course, un PATCH idempotent non.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth.models import (
    CHANNELS,
    JOBS,
    ROLE_ADMIN,
    ROLES,
    User,
)


class LastAdminError(ValueError):
    """Reste une ValueError — les appelants qui attrapent large (CLI, tests) ne
    changent pas — mais permet à l'API de répondre 409 plutôt que 400 : ce n'est
    pas la requête qui est mal formée, c'est l'état du studio qui l'interdit.
    """


def list_members(db: Session) -> list[User]:
    """Les membres, admins d'abord puis par nom.

    Le tri se fait en Python sur `name` et non en SQL sur `display_name` : le nom
    affiché retombe sur l'email quand `display_name` est nul (comptes créés par
    la CLI avant ce module), et un ORDER BY sur la colonne rangerait ces
    comptes-là au milieu des NULL plutôt qu'à leur place alphabétique.
    """
    users = list(db.scalars(select(User)))
    users.sort(key=lambda u: (not u.is_admin, u.name.casefold()))
    return users


def get_member(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def _active_admin_count(db: Session, excluding: int | None = None) -> int:
    stmt = select(func.count(User.id)).where(
        User.role == ROLE_ADMIN, User.active.is_(True)
    )
    if excluding is not None:
        stmt = stmt.where(User.id != excluding)
    return int(db.scalar(stmt) or 0)


def _assert_not_last_admin(db: Session, user: User) -> None:
    """Interdit de retirer les droits du dernier administrateur actif.

    Se verrouiller dehors de sa propre application est irréversible depuis l'UI :
    il faudrait un accès shell à la base pour se rouvrir la porte. Le refus vaut
    mieux que la réparation.
    """
    if not (user.is_admin and user.active):
        return
    if _active_admin_count(db, excluding=user.id) == 0:
        raise LastAdminError(
            "Impossible : c'est le dernier administrateur actif. "
            "Nommez un autre administrateur avant de modifier celui-ci."
        )


def update_member(
    db: Session,
    user: User,
    display_name: str | None = None,
    job: str | None = None,
    role: str | None = None,
    contact_channel: str | None = None,
    whatsapp_number: str | None = None,
    discord_user_id: str | None = None,
) -> User:
    """Met à jour la fiche d'un membre. Seuls les champs fournis sont touchés.

    Les énumérations sont validées ici et pas seulement à la frontière HTTP : la
    CLI et les tâches planifiées passent par le même service, et un `job` libre
    ferait diverger le libellé affiché de ce que le formulaire propose — c'est
    exactement ce qui laissait « Tom, Nadia & Iliès » exister comme un métier.
    """
    if job is not None and job not in JOBS:
        raise ValueError(f"Métier invalide : {job}")
    if role is not None and role not in ROLES:
        raise ValueError(f"Rôle invalide : {role}")
    if contact_channel is not None and contact_channel not in CHANNELS:
        raise ValueError(f"Canal de contact invalide : {contact_channel}")

    if role is not None and role != ROLE_ADMIN:
        _assert_not_last_admin(db, user)

    if display_name is not None:
        # Une chaîne vide efface le nom choisi : `User.name` retombe alors sur
        # l'email plutôt que d'afficher un libellé vide.
        user.display_name = display_name.strip() or None
    if job is not None:
        user.job = job
    if role is not None:
        user.role = role
    if contact_channel is not None:
        user.contact_channel = contact_channel
    if whatsapp_number is not None:
        user.whatsapp_number = whatsapp_number.strip() or None
    if discord_user_id is not None:
        user.discord_user_id = discord_user_id.strip() or None

    db.commit()
    db.refresh(user)
    return user


def set_permissions(
    db: Session,
    user: User,
    can_manage_photos: bool | None = None,
    can_view_pay: bool | None = None,
) -> User:
    """Pose les permissions à la valeur voulue. IDEMPOTENT : rejouer l'appel ne
    change rien, contrairement au `togglePhotos(i)` du prototype où deux clics
    concurrents s'annulaient (ou pire, se doublaient) selon l'ordre d'arrivée.

    `None` signifie « ne touche pas à cette permission », pas « mets-la à faux ».
    """
    if can_manage_photos is not None:
        user.can_manage_photos = bool(can_manage_photos)
    if can_view_pay is not None:
        user.can_view_pay = bool(can_view_pay)
    db.commit()
    db.refresh(user)
    return user


def deactivate_member(db: Session, user: User) -> User:
    """Sort un membre du studio sans effacer son passage.

    On ne supprime pas la ligne : les tâches, les épisodes et les ressources
    pointent dessus. Un DELETE ferait soit tomber les clés étrangères, soit
    orpheliner l'historique — « qui a monté cet épisode ? » deviendrait
    indéterminable.
    """
    _assert_not_last_admin(db, user)
    user.active = False
    db.commit()
    db.refresh(user)
    return user
