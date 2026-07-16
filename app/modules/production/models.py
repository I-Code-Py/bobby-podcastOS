"""Domaine production : épisodes, pipeline, tâches, ressources, affectations.

Ce module traduit en base ce que le prototype v2 gardait en mémoire. Trois
principes ont guidé la modélisation :

1. Rien de présentationnel n'est stocké. Le prototype persistait des initiales,
   des couleurs d'avatar, des dégradés CSS, des pourcentages pré-calculés et des
   libellés figés (« sous 3 j », « J − 7 », « 5 / 11 tâches »). Tout cela se
   dérive de la donnée réelle et se calcule à l'affichage — le stocker, c'est
   garantir qu'un jour ça mentira.

2. Une personne est une ligne, pas cinq. Le prototype décrivait le même humain
   dans TEAM, ROLES, MEMBERS, CREW et EP_ROLES, reliés par une chaîne tantôt
   « Bobby », tantôt « BS », tantôt « Sofia · monteuse ». Ici, tout pointe vers
   `users.id`.

3. Une seule table de tâches. Le prototype en avait cinq (TASKS, genTasks,
   Episode.tasks, EXTRA.doNow, STEP_TASKS + la map `checked` séparée). Elles
   décrivent la même chose : un travail, pour quelqu'un, pour une date.
"""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# ---------------------------------------------------------------------------
# Le pipeline : 6 phases ordonnées (constante PHASES du prototype)
# ---------------------------------------------------------------------------
PHASE_BOOKING = "booking"
PHASE_TOURNAGE = "tournage"
PHASE_ETALONNAGE = "etalonnage"
PHASE_MONTAGES = "montages"
PHASE_MINIATURE_DERUSH = "miniature_derush"
PHASE_PUBLICATION = "publication"

# L'ORDRE fait foi : l'avancement d'un épisode est l'index de sa phase ici.
PHASES = (
    PHASE_BOOKING,
    PHASE_TOURNAGE,
    PHASE_ETALONNAGE,
    PHASE_MONTAGES,
    PHASE_MINIATURE_DERUSH,
    PHASE_PUBLICATION,
)

PHASE_LABELS = {
    PHASE_BOOKING: "Booking",
    PHASE_TOURNAGE: "Tournage",
    PHASE_ETALONNAGE: "Étalonnage",
    PHASE_MONTAGES: "Montages",
    PHASE_MINIATURE_DERUSH: "Miniature & Dérush",
    PHASE_PUBLICATION: "Publication",
}

# ---------------------------------------------------------------------------
# États d'une tâche
# ---------------------------------------------------------------------------
TASK_TODO = "todo"
TASK_DONE = "done"
# `cancelled` est réservé aux admins et ne se défait qu'explicitement
# (« Rétablir »). Une seule tâche annulée marque toute l'étape comme annulée.
TASK_CANCELLED = "cancelled"
TASK_STATES = (TASK_TODO, TASK_DONE, TASK_CANCELLED)

# Origine d'une tâche : d'où elle vient, ce qui conditionne si on peut la
# supprimer et comment l'expliquer à l'utilisateur.
ORIGIN_TEMPLATE = "template"  # instanciée à la création de l'épisode
ORIGIN_MANUAL = "manual"  # créée à la main
ORIGIN_RESOURCE = "resource"  # engendrée par le dépôt d'un livrable
TASK_ORIGINS = (ORIGIN_TEMPLATE, ORIGIN_MANUAL, ORIGIN_RESOURCE)

# ---------------------------------------------------------------------------
# Types de livrables déposés sur un épisode
# ---------------------------------------------------------------------------
RESOURCE_MONTAGE = "montage"
RESOURCE_RUSH = "rush"
RESOURCE_AUDIO = "audio"
RESOURCE_MINIATURE = "miniature"
RESOURCE_MASTER = "master"
RESOURCE_AUTRE = "autre"
RESOURCE_KINDS = (
    RESOURCE_MONTAGE,
    RESOURCE_RUSH,
    RESOURCE_AUDIO,
    RESOURCE_MINIATURE,
    RESOURCE_MASTER,
    RESOURCE_AUTRE,
)

RESOURCE_LABELS = {
    RESOURCE_MONTAGE: "Montage",
    RESOURCE_RUSH: "Rush vidéo",
    RESOURCE_AUDIO: "Audio",
    RESOURCE_MINIATURE: "Miniature",
    RESOURCE_MASTER: "Master",
    RESOURCE_AUTRE: "Autre",
}

# ---------------------------------------------------------------------------
# Rôles affectables sur un épisode (panneau « Qui gère quoi »)
# ---------------------------------------------------------------------------
EP_ROLE_MONTAGE_INTRO = "montage_intro"
EP_ROLE_MONTAGE_PODCAST = "montage_podcast"
EP_ROLE_MONTEUR_COURT = "monteur_court"
EP_ROLE_DERUSH = "derush"
EP_ROLE_MINIATURE = "miniature"
EPISODE_ROLES = (
    EP_ROLE_MONTAGE_INTRO,
    EP_ROLE_MONTAGE_PODCAST,
    EP_ROLE_MONTEUR_COURT,
    EP_ROLE_DERUSH,
    EP_ROLE_MINIATURE,
)

EPISODE_ROLE_LABELS = {
    EP_ROLE_MONTAGE_INTRO: "Montage intro",
    EP_ROLE_MONTAGE_PODCAST: "Montage podcast",
    EP_ROLE_MONTEUR_COURT: "Monteur court",
    EP_ROLE_DERUSH: "Dérush",
    EP_ROLE_MINIATURE: "Miniature",
}


class Episode(Base):
    """Un épisode de podcast, du booking à la publication.

    Le prototype portait deux identifiants pour la même chose (`'ep24'` en clé
    de Record et `'EP24'` en champ `ep`) : il ne reste qu'un `id` et un `number`.
    """

    __tablename__ = "episodes"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Numéro affiché (« EP24 »). Attribué par le serveur, pas par un compteur
    # côté client comme le faisait `epn`.
    number: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    guest: Mapped[str] = mapped_column(String(200))

    # Phase courante. Le prototype avait un `idx` que rien n'incrémentait ;
    # l'avancement est ici une vraie transition (voir episode_service).
    phase: Mapped[str] = mapped_column(String(30), default=PHASE_BOOKING)

    # Archivage réversible (le menu contextuel du prototype est une bascule).
    # Remplace la double vérité `Episode.done` + `state.doneKeys`.
    archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # Date de publication visée. Le prototype stockait « 22 juillet », « 08/07 »
    # ou « à caler » dans le même champ texte : ici une vraie date, nullable
    # quand elle reste à caler.
    publish_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    shoot_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Les deux visuels sont sémantiquement distincts : la photo ronde de
    # l'invité et la miniature 16:9 de la carte.
    guest_photo_url: Mapped[str | None] = mapped_column(String(700), nullable=True)
    cover_url: Mapped[str | None] = mapped_column(String(700), nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tasks: Mapped[list["Task"]] = relationship(
        back_populates="episode", cascade="all, delete-orphan"
    )
    resources: Mapped[list["EpisodeResource"]] = relationship(
        back_populates="episode", cascade="all, delete-orphan"
    )
    assignments: Mapped[list["EpisodeAssignment"]] = relationship(
        back_populates="episode", cascade="all, delete-orphan"
    )

    @property
    def phase_index(self) -> int:
        """Rang de la phase courante (l'ancien `idx`), dérivé et non stocké."""
        try:
            return PHASES.index(self.phase)
        except ValueError:
            return 0

    @property
    def phase_label(self) -> str:
        return PHASE_LABELS.get(self.phase, self.phase)


class EpisodeResource(Base):
    """Un livrable déposé sur un épisode (rush, audio, montage, miniature…).

    Déposer un livrable engendre la tâche du maillon suivant — c'est la règle
    métier centrale du studio. Le lien est matérialisé par `Task.resource_id`,
    que le prototype ne posait pas alors que c'était tout le sens de la chose.
    """

    __tablename__ = "episode_resources"

    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[int] = mapped_column(
        ForeignKey("episodes.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(String(700))

    # « Toi » était écrit en dur dans le prototype : c'est l'utilisateur connecté.
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    episode: Mapped[Episode] = relationship(back_populates="resources")
    generated_tasks: Mapped[list["Task"]] = relationship(back_populates="resource")

    @property
    def kind_label(self) -> str:
        return RESOURCE_LABELS.get(self.kind, self.kind)


class Task(Base):
    """Un travail à faire, pour quelqu'un, pour une date.

    Table unique là où le prototype en avait cinq (TASKS statiques, genTasks,
    Episode.tasks, EXTRA.doNow, STEP_TASKS) plus une map `checked` séparée,
    non persistante et sans trace de qui avait coché.

    `episode_id` est nullable : le prototype avait une clé polymorphe `epKey`
    pouvant valoir `'clip'`, qui n'est pas un épisode mais le contexte clipping.
    Une tâche sans épisode est une tâche de clipping.
    """

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[int | None] = mapped_column(
        ForeignKey("episodes.id", ondelete="CASCADE"), nullable=True, index=True
    )

    # Renseignée pour les tâches du pipeline (issues du template), nulle sinon.
    phase: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Ordre dans la checklist de la phase.
    position: Mapped[int] = mapped_column(Integer, default=0)

    label: Mapped[str] = mapped_column(String(300))
    state: Mapped[str] = mapped_column(String(20), default=TASK_TODO, index=True)
    origin: Mapped[str] = mapped_column(String(20), default=ORIGIN_MANUAL)

    # Vraie date d'échéance. Le prototype affichait « sous 3 j » sans jamais
    # calculer la date, et figeait toute tâche générée au 2026-07-17.
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)

    assignee_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # La ressource dont cette tâche découle, quand origin == resource.
    resource_id: Mapped[int | None] = mapped_column(
        ForeignKey("episode_resources.id", ondelete="SET NULL"), nullable=True
    )

    # Qui a coché, et quand : n'existait nulle part dans le prototype.
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    episode: Mapped[Episode | None] = relationship(back_populates="tasks")
    resource: Mapped[EpisodeResource | None] = relationship(back_populates="generated_tasks")

    @property
    def is_clipping(self) -> bool:
        return self.episode_id is None


class EpisodeAssignment(Base):
    """Qui tient quel poste sur CET épisode (panneau « Qui gère quoi »).

    Le prototype affichait la constante globale EP_ROLES, identique pour tous
    les épisodes : la vue ne la reliait jamais à l'épisode sélectionné. C'est
    pourtant ce qui doit décider à qui revient une tâche générée — le monteur
    de l'EP24 n'est pas forcément celui de l'EP26.
    """

    __tablename__ = "episode_assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[int] = mapped_column(
        ForeignKey("episodes.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(30))
    member_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))

    episode: Mapped[Episode] = relationship(back_populates="assignments")

    @property
    def role_label(self) -> str:
        return EPISODE_ROLE_LABELS.get(self.role, self.role)
