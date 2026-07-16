from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# Rôle d'AUTORISATION : ce que le compte a le droit de faire.
ROLE_ADMIN = "admin"
ROLE_VIEWER = "viewer"
ROLES = (ROLE_ADMIN, ROLE_VIEWER)

# Rôle MÉTIER : ce que la personne fait au studio. À ne pas confondre avec
# ci-dessus — le prototype mélangeait les deux, « admin » y étant à la fois un
# rôle d'autorisation et une option du formulaire d'invitation.
JOB_PILOTE = "pilote"
JOB_MONTEUR = "monteur"
JOB_MONTEUR_COURT = "monteur_court"
JOB_FILMMAKER = "filmmaker"
JOB_MINIATURISTE = "miniaturiste"
JOB_CLIPPEUR = "clippeur"
JOBS = (
    JOB_PILOTE,
    JOB_MONTEUR,
    JOB_MONTEUR_COURT,
    JOB_FILMMAKER,
    JOB_MINIATURISTE,
    JOB_CLIPPEUR,
)

JOB_LABELS = {
    JOB_PILOTE: "Pilote",
    JOB_MONTEUR: "Monteur",
    JOB_MONTEUR_COURT: "Monteur court",
    JOB_FILMMAKER: "Filmmaker",
    JOB_MINIATURISTE: "Miniaturiste",
    JOB_CLIPPEUR: "Clippeur",
}

# Cycle de vie d'un membre.
MEMBER_ACTIVE = "active"
MEMBER_INVITED = "invited"  # invité, n'a pas encore choisi de mot de passe
MEMBER_STATUSES = (MEMBER_ACTIVE, MEMBER_INVITED)

# Canaux de contact.
CHANNEL_DISCORD = "discord"
CHANNEL_WHATSAPP = "whatsapp"
CHANNELS = (CHANNEL_DISCORD, CHANNEL_WHATSAPP)


class User(Base):
    """Un humain du studio : son compte, son métier, ses droits, son contact.

    Le prototype décrivait la même personne dans cinq listes non reliées (TEAM,
    ROLES, MEMBERS, CREW, EP_ROLES), jointes par une chaîne tantôt « Bobby »,
    tantôt « BS », tantôt « Sofia · monteuse » — toute jointure naïve échouait
    silencieusement pour la moitié des lignes. Ici, une personne est une ligne.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    # Nullable : un membre invité n'a pas encore choisi son mot de passe.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(20), default=ROLE_VIEWER)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # --- Identité affichable -------------------------------------------------
    # Le nom montré partout (« Bobby »). Les initiales (« BS ») s'en dérivent :
    # les stocker, c'est risquer qu'elles divergent du nom.
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    job: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=MEMBER_ACTIVE)

    # --- Contact -------------------------------------------------------------
    # Le prototype avait un champ `to` polymorphe : un numéro de téléphone pour
    # WhatsApp, une URL de salon pour Discord. Deux notions, deux colonnes.
    contact_channel: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # WhatsApp : numéro E.164 sans le « + » (format attendu par Evolution API).
    whatsapp_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Discord : identifiant de l'utilisateur, pour un message privé — le
    # prototype pointait des salons partagés (/general, /clips) et appelait ça
    # « envoyer à Bobby ».
    discord_user_id: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # --- Permissions ---------------------------------------------------------
    # Les deux colonnes du tableau « Rôles & permissions ». Dans le prototype
    # elles étaient écrites mais jamais lues : elles n'autorisaient rien.
    #
    # « PHOTOS ÉPISODE » : déposer/remplacer la photo d'invité et la miniature.
    can_manage_photos: Mapped[bool] = mapped_column(Boolean, default=False)
    # « VOIT LA PAIE » : voir les montants dus aux clippeurs et le barème. Le
    # pendant exact de la distinction déjà en place entre les deux webhooks
    # Discord (rapport public sans montants / rapport staff avec montants).
    can_view_pay: Mapped[bool] = mapped_column(Boolean, default=False)

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    @property
    def name(self) -> str:
        """Nom à afficher, avec repli sur l'email pour les comptes historiques."""
        return self.display_name or self.email.split("@")[0]

    @property
    def initials(self) -> str:
        """Dérivées du nom — jamais stockées."""
        parts = [p for p in self.name.replace(".", " ").replace("_", " ").split() if p]
        if not parts:
            return "??"
        if len(parts) == 1:
            return parts[0][:2].upper()
        return (parts[0][0] + parts[1][0]).upper()

    @property
    def sees_money(self) -> bool:
        """Un admin voit toujours la paie ; les autres selon leur permission."""
        return self.is_admin or self.can_view_pay
