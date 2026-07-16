"""Vue « Épisodes » du SPA : le pipeline, les livrables et qui gère quoi.

Tout ce que la maquette dessinait en dur sort d'ici calculé : les initiales de
l'invité se dérivent de son nom, la progression se compte sur les tâches, et le
libellé d'une phase vient de la constante serveur — pas d'un texte figé dans le
navigateur, qu'un renommage aurait laissé mentir.
"""

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_api_user, require_api_admin, verify_csrf_header
from app.api.schemas import ApiModel
from app.core.auth.models import User
from app.db import get_db
from app.modules.production.models import (
    PHASE_LABELS,
    PHASES,
    Episode,
    EpisodeResource,
    Task,
)
from app.modules.production.services import episode_service

router = APIRouter(prefix="/api/v2", tags=["episodes"])

# Les tâches hors pipeline (créées à la main, ou engendrées par un livrable)
# n'appartiennent à aucune phase : elles forment un groupe à part plutôt que
# d'être rattachées d'office au booking.
OFF_PIPELINE_LABEL = "Hors pipeline"


# ---------------------------------------------------------------------------
# Schémas
# ---------------------------------------------------------------------------


class AssignmentOut(ApiModel):
    role: str
    role_label: str
    member_id: int
    member_name: str


class EpisodeOut(ApiModel):
    id: int
    number: int
    guest: str
    """Dérivées du nom de l'invité — jamais stockées, sans quoi renommer
    l'invité laisserait les initiales d'hier."""
    initials: str
    phase: str
    phase_index: int
    phase_label: str
    archived: bool
    publish_date: date | None
    shoot_date: date | None
    progress_percent: int
    task_count: int
    done_count: int
    resource_count: int
    guest_photo_url: str | None
    cover_url: str | None
    assignments: list[AssignmentOut]


class TaskOut(ApiModel):
    id: int
    label: str
    state: str
    origin: str
    position: int
    phase: str | None
    due_date: date | None
    assignee_id: int | None
    assignee_name: str | None
    assignee_initials: str | None
    resource_id: int | None
    completed_at: datetime | None


class TaskGroupOut(ApiModel):
    """Les tâches d'une étape du pipeline, dans l'ordre de la checklist."""

    phase: str | None
    phase_label: str
    tasks: list[TaskOut]


class ResourceOut(ApiModel):
    id: int
    kind: str
    kind_label: str
    title: str
    url: str
    created_by_id: int | None
    created_by_name: str | None
    created_at: datetime | None


class EpisodeDetailOut(EpisodeOut):
    notes: str | None
    tasks: list[TaskGroupOut]
    resources: list[ResourceOut]


class EpisodeCreateIn(ApiModel):
    guest: str
    shoot_date: date | None = None
    publish_date: date | None = None
    """{rôle: id du membre}. Ce qui décide à qui reviennent les tâches du
    template — le prototype les câblait sur des prénoms."""
    assignments: dict[str, int | None] | None = None


class EpisodeUpdateIn(ApiModel):
    guest: str | None = None
    publish_date: date | None = None
    shoot_date: date | None = None
    phase: str | None = None
    assignments: dict[str, int | None] | None = None


class ResourceCreateIn(ApiModel):
    kind: str
    title: str
    url: str


class ResourceCreatedOut(ApiModel):
    """Le dépôt renvoie AUSSI la tâche engendrée : c'est elle le résultat utile
    du geste, et le SPA doit pouvoir l'afficher sans recharger l'épisode."""

    resource: ResourceOut
    task: TaskOut


# ---------------------------------------------------------------------------
# Sérialisation
# ---------------------------------------------------------------------------


def _initials(name: str) -> str:
    parts = [p for p in name.replace("_", " ").replace("-", " ").split() if p]
    if not parts:
        return "??"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()


def _users_by_id(db: Session, user_ids: set[int]) -> dict[int, User]:
    """Les membres cités par un lot d'épisodes, en une requête.

    Les affectations et les tâches ne portent qu'un `user_id` : les résoudre un
    par un rendrait la liste linéaire en nombre d'intervenants.
    """
    ids = {uid for uid in user_ids if uid is not None}
    if not ids:
        return {}
    return {u.id: u for u in db.scalars(select(User).where(User.id.in_(ids)))}


def _assignments_out(episode: Episode, users: dict[int, User]) -> list[AssignmentOut]:
    out = [
        AssignmentOut(
            role=a.role,
            role_label=a.role_label,
            member_id=a.member_id,
            # Un compte supprimé laisse l'affectation orpheline : on le dit
            # plutôt que d'afficher un trou.
            member_name=users[a.member_id].name if a.member_id in users else "Inconnu",
        )
        for a in episode.assignments
    ]
    out.sort(key=lambda a: a.role_label)
    return out


def _episode_fields(db: Session, episode: Episode, users: dict[int, User]) -> dict:
    stats = episode_service.progress(db, episode)
    return {
        "id": episode.id,
        "number": episode.number,
        "guest": episode.guest,
        "initials": _initials(episode.guest),
        "phase": episode.phase,
        "phase_index": episode.phase_index,
        "phase_label": episode.phase_label,
        "archived": episode.archived,
        "publish_date": episode.publish_date,
        "shoot_date": episode.shoot_date,
        "progress_percent": stats["percent"],
        "task_count": stats["task_count"],
        "done_count": stats["done_count"],
        "resource_count": len(episode.resources),
        "guest_photo_url": episode.guest_photo_url,
        "cover_url": episode.cover_url,
        "assignments": _assignments_out(episode, users),
    }


def _task_out(task: Task, users: dict[int, User]) -> TaskOut:
    assignee = users.get(task.assignee_id) if task.assignee_id else None
    return TaskOut(
        id=task.id,
        label=task.label,
        state=task.state,
        origin=task.origin,
        position=task.position,
        phase=task.phase,
        due_date=task.due_date,
        assignee_id=task.assignee_id,
        assignee_name=assignee.name if assignee else None,
        assignee_initials=assignee.initials if assignee else None,
        resource_id=task.resource_id,
        completed_at=task.completed_at,
    )


def _task_groups(episode: Episode, users: dict[int, User]) -> list[TaskGroupOut]:
    """Groupe les tâches par phase, dans l'ordre du pipeline.

    Une phase sans tâche apparaît quand même : l'étape existe dans le pipeline,
    la masquer ferait croire qu'elle a disparu.
    """
    by_phase: dict[str | None, list[Task]] = {}
    for task in episode.tasks:
        key = task.phase if task.phase in PHASES else None
        by_phase.setdefault(key, []).append(task)

    groups = [
        TaskGroupOut(
            phase=phase,
            phase_label=PHASE_LABELS[phase],
            tasks=[
                _task_out(t, users)
                for t in sorted(by_phase.get(phase, []), key=lambda t: (t.position, t.id))
            ],
        )
        for phase in PHASES
    ]
    off_pipeline = by_phase.get(None, [])
    if off_pipeline:
        groups.append(
            TaskGroupOut(
                phase=None,
                phase_label=OFF_PIPELINE_LABEL,
                # Les plus urgentes d'abord ; une tâche sans échéance ferme la marche.
                tasks=[
                    _task_out(t, users)
                    for t in sorted(
                        off_pipeline, key=lambda t: (t.due_date is None, t.due_date, t.id)
                    )
                ],
            )
        )
    return groups


def _resource_out(resource: EpisodeResource, users: dict[int, User]) -> ResourceOut:
    author = users.get(resource.created_by_id) if resource.created_by_id else None
    return ResourceOut(
        id=resource.id,
        kind=resource.kind,
        kind_label=resource.kind_label,
        title=resource.title,
        url=resource.url,
        created_by_id=resource.created_by_id,
        # « Toi » était écrit en dur dans la maquette.
        created_by_name=author.name if author else None,
        created_at=resource.created_at,
    )


def _cited_user_ids(episodes: list[Episode]) -> set[int]:
    ids: set[int] = set()
    for episode in episodes:
        ids.update(a.member_id for a in episode.assignments)
        ids.update(t.assignee_id for t in episode.tasks if t.assignee_id)
        ids.update(r.created_by_id for r in episode.resources if r.created_by_id)
    return ids


def _load_episode(db: Session, episode_id: int) -> Episode:
    episode = episode_service.get_episode(db, episode_id)
    if episode is None:
        raise HTTPException(status_code=404, detail="Épisode introuvable")
    return episode


def _detail(db: Session, episode: Episode) -> EpisodeDetailOut:
    users = _users_by_id(db, _cited_user_ids([episode]))
    return EpisodeDetailOut(
        **_episode_fields(db, episode, users),
        notes=episode.notes,
        tasks=_task_groups(episode, users),
        resources=[_resource_out(r, users) for r in episode_service.list_resources(db, episode)],
    )


# ---------------------------------------------------------------------------
# Lecture
# ---------------------------------------------------------------------------


@router.get("/episodes", response_model=list[EpisodeOut])
def list_episodes(
    archived: bool = False,
    db: Session = Depends(get_db),
    _user: User = Depends(get_api_user),
):
    """Le pipeline. `archived=true` donne la corbeille — la même liste, l'autre
    versant de la bascule d'archivage."""
    episodes = episode_service.list_episodes(db, archived=archived)
    users = _users_by_id(db, _cited_user_ids(episodes))
    return [EpisodeOut(**_episode_fields(db, episode, users)) for episode in episodes]


@router.get("/episodes/{episode_id}", response_model=EpisodeDetailOut)
def read_episode(
    episode_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_api_user),
):
    return _detail(db, _load_episode(db, episode_id))


# ---------------------------------------------------------------------------
# Écriture
# ---------------------------------------------------------------------------


@router.post("/episodes", response_model=EpisodeDetailOut, status_code=201)
def create_episode(
    payload: EpisodeCreateIn,
    db: Session = Depends(get_db),
    admin: User = Depends(require_api_admin),
    _csrf: None = Depends(verify_csrf_header),
):
    """Crée l'épisode et déroule ses 15 tâches. Le créateur en est le pilote."""
    try:
        episode = episode_service.create_episode(
            db,
            guest=payload.guest,
            created_by=admin,
            shoot_date=payload.shoot_date,
            publish_date=payload.publish_date,
            assignments=payload.assignments,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _detail(db, episode)


@router.patch("/episodes/{episode_id}", response_model=EpisodeDetailOut)
def update_episode(
    episode_id: int,
    payload: EpisodeUpdateIn,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_api_admin),
    _csrf: None = Depends(verify_csrf_header),
):
    """Modifie l'épisode. Les champs absents restent inchangés — un PATCH ne
    doit jamais effacer ce dont il n'a pas parlé."""
    episode = _load_episode(db, episode_id)
    try:
        episode_service.update_episode(
            db,
            episode,
            guest=payload.guest,
            publish_date=payload.publish_date,
            shoot_date=payload.shoot_date,
        )
        if payload.phase is not None:
            episode_service.set_phase(db, episode, payload.phase)
        if payload.assignments is not None:
            episode_service.set_assignments(db, episode, payload.assignments)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _detail(db, episode)


@router.post("/episodes/{episode_id}/archive", response_model=EpisodeDetailOut)
def archive_episode(
    episode_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_api_admin),
    _csrf: None = Depends(verify_csrf_header),
):
    episode = _load_episode(db, episode_id)
    episode_service.archive(db, episode)
    return _detail(db, episode)


@router.post("/episodes/{episode_id}/unarchive", response_model=EpisodeDetailOut)
def unarchive_episode(
    episode_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_api_admin),
    _csrf: None = Depends(verify_csrf_header),
):
    episode = _load_episode(db, episode_id)
    episode_service.unarchive(db, episode)
    return _detail(db, episode)


@router.delete("/episodes/{episode_id}", status_code=204)
def delete_episode(
    episode_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_api_admin),
    _csrf: None = Depends(verify_csrf_header),
):
    """Suppression définitive, tâches et livrables compris. L'archivage est la
    porte de sortie réversible ; celle-ci ne l'est pas."""
    episode_service.delete_episode(db, _load_episode(db, episode_id))


# ---------------------------------------------------------------------------
# Livrables
# ---------------------------------------------------------------------------


@router.get("/episodes/{episode_id}/resources", response_model=list[ResourceOut])
def list_resources(
    episode_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_api_user),
):
    episode = _load_episode(db, episode_id)
    users = _users_by_id(db, {r.created_by_id for r in episode.resources if r.created_by_id})
    return [_resource_out(r, users) for r in episode_service.list_resources(db, episode)]


@router.post(
    "/episodes/{episode_id}/resources", response_model=ResourceCreatedOut, status_code=201
)
def add_resource(
    episode_id: int,
    payload: ResourceCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_api_user),
    _csrf: None = Depends(verify_csrf_header),
):
    """Dépose un livrable — geste ouvert à toute l'équipe, c'est son travail.

    La réponse porte la tâche engendrée : déposer un rush met le monteur au
    travail, et l'auteur du dépôt doit voir ce qu'il vient de déclencher.
    """
    episode = _load_episode(db, episode_id)
    try:
        resource, task = episode_service.add_resource(
            db,
            episode,
            kind=payload.kind,
            title=payload.title,
            url=payload.url,
            created_by=user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    users = _users_by_id(db, {resource.created_by_id, task.assignee_id} - {None})
    return ResourceCreatedOut(
        resource=_resource_out(resource, users), task=_task_out(task, users)
    )
