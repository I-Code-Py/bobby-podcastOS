"""Vue « Tâches » du SPA : ce qu'il y a à faire, pour qui, pour quand.

Ce routeur ne transporte que des dates et des états. Le prototype envoyait des
libellés figés (« sous 3 j », « jeudi 17 », « AUJOURD'HUI ») et groupait ses
tâches par un dictionnaire `DAY_META` de cinq dates écrites en dur, avec
« aujourd'hui » valant la constante '2026-07-15' : l'application ne fonctionnait
littéralement que pendant la semaine du 15 juillet 2026. Le groupement par jour
et l'urgence se calculent à l'affichage, à partir de la vraie date du client et
de la vraie échéance de la tâche.

Même règle pour l'identité : on expose `assigneeId`, le nom et les initiales
dérivées, jamais la chaîne « BS » sur laquelle le prototype comparait `av === 'BS'`
pour décider du badge « À TOI ». Ce badge, c'est `isMine`, résolu ici contre
l'utilisateur de la session.
"""

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_api_user, require_api_admin, verify_csrf_header
from app.api.schemas import ApiModel
from app.core.auth.models import User
from app.db import get_db
from app.modules.production.models import TASK_DONE, TASK_STATES, TASK_TODO, Task
from app.modules.production.services import task_service

router = APIRouter(prefix="/api/v2", tags=["tasks"])


class TaskOut(ApiModel):
    id: int
    label: str
    state: str
    origin: str
    """L'échéance, nue. Le prototype doublait cette date d'un champ `due` figé
    (« sous 3 j ») qui ne se recalculait jamais et finissait par la contredire."""
    due_date: date | None
    episode_id: int | None
    episode_number: int | None
    episode_guest: str | None
    phase: str | None
    assignee_id: int | None
    assignee_name: str | None
    assignee_initials: str | None
    """Le badge « À TOI » : l'assigné est l'utilisateur de la session."""
    is_mine: bool
    resource_id: int | None
    completed_at: datetime | None
    completed_by_name: str | None
    """Une tâche sans épisode est une tâche de clipping."""
    is_clipping: bool


class TaskCreateIn(ApiModel):
    label: str
    episode_id: int | None = None
    assignee_id: int | None = None
    due_date: date | None = None
    phase: str | None = None


class TaskUpdateIn(ApiModel):
    label: str | None = None
    due_date: date | None = None
    assignee_id: int | None = None
    state: str | None = None


def _task_out(task: Task, users: dict[int, User], current_user: User) -> TaskOut:
    assignee = users.get(task.assignee_id) if task.assignee_id else None
    completed_by = users.get(task.completed_by_id) if task.completed_by_id else None
    return TaskOut(
        id=task.id,
        label=task.label,
        state=task.state,
        origin=task.origin,
        due_date=task.due_date,
        episode_id=task.episode_id,
        episode_number=task.episode.number if task.episode else None,
        episode_guest=task.episode.guest if task.episode else None,
        phase=task.phase,
        assignee_id=task.assignee_id,
        assignee_name=assignee.name if assignee else None,
        # Dérivées de User.initials : les stocker, c'est risquer qu'elles
        # divergent du nom — c'est exactement ce qui arrivait au prototype.
        assignee_initials=assignee.initials if assignee else None,
        is_mine=task.assignee_id is not None and task.assignee_id == current_user.id,
        resource_id=task.resource_id,
        completed_at=task.completed_at,
        completed_by_name=completed_by.name if completed_by else None,
        is_clipping=task.is_clipping,
    )


def _one(db: Session, task: Task, current_user: User) -> TaskOut:
    return _task_out(task, task_service.load_users(db, [task]), current_user)


def _get_or_404(db: Session, task_id: int) -> Task:
    task = task_service.get_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Tâche introuvable")
    return task


def _guard_state(state: str, user: User) -> None:
    """Annuler est réservé aux admins : le service dit quels états l'exigent, le
    routeur connaît la session et tranche.

    Appelé AVANT toute écriture : un PATCH qui renomme et annule d'un même geste
    ne doit pas laisser le renommage derrière lui s'il finit en 403.
    """
    if state not in TASK_STATES:
        raise HTTPException(status_code=400, detail="État de tâche inconnu")
    if task_service.requires_admin(state) and not user.is_admin:
        raise HTTPException(
            status_code=403, detail="Seul un administrateur peut annuler une tâche"
        )


def _set_state(db: Session, task: Task, state: str, user: User) -> Task:
    _guard_state(state, user)
    try:
        return task_service.set_state(db, task, state, user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(
    mine: bool = False,
    episode_id: int | None = Query(None, alias="episodeId"),
    include_done: bool = Query(True, alias="includeDone"),
    db: Session = Depends(get_db),
    user: User = Depends(get_api_user),
):
    """La liste, déjà triée. Le SPA n'a pas à retrier : à échéance égale, l'ordre
    doit être le même d'un appel à l'autre, ce que seul le serveur peut garantir."""
    tasks = task_service.list_tasks(
        db,
        assignee_id=user.id if mine else None,
        episode_id=episode_id,
        include_done=include_done,
    )
    users = task_service.load_users(db, tasks)
    return [_task_out(task, users, user) for task in tasks]


@router.post("/tasks", response_model=TaskOut, status_code=201)
def create_task(
    payload: TaskCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_api_user),
    _csrf: None = Depends(verify_csrf_header),
):
    try:
        task = task_service.create_task(
            db,
            label=payload.label,
            created_by=user,
            episode_id=payload.episode_id,
            assignee_id=payload.assignee_id,
            due_date=payload.due_date,
            phase=payload.phase,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _one(db, task, user)


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(
    task_id: int,
    payload: TaskUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_api_user),
    _csrf: None = Depends(verify_csrf_header),
):
    """Mise à jour partielle : seuls les champs présents dans le corps bougent.

    On lit `model_fields_set` plutôt que de tester `is None`, sinon envoyer
    `dueDate: null` (« retire l'échéance ») serait indiscernable de ne pas
    envoyer `dueDate` du tout, et effacer une échéance deviendrait impossible.
    """
    task = _get_or_404(db, task_id)
    sent = payload.model_fields_set

    if payload.state is not None:
        _guard_state(payload.state, user)

    try:
        task = task_service.update_task(
            db,
            task,
            label=payload.label,
            due_date=payload.due_date if "due_date" in sent else task_service.UNSET,
            assignee_id=(
                payload.assignee_id if "assignee_id" in sent else task_service.UNSET
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if payload.state is not None:
        task = _set_state(db, task, payload.state, user)
    return _one(db, task, user)


@router.post("/tasks/{task_id}/complete", response_model=TaskOut)
def complete_task(
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_api_user),
    _csrf: None = Depends(verify_csrf_header),
):
    """Le raccourci de la case à cocher — l'aller du toggle que le prototype
    tenait dans une map `checked` en mémoire, partagée par tous les visiteurs."""
    task = _get_or_404(db, task_id)
    return _one(db, _set_state(db, task, TASK_DONE, user), user)


@router.post("/tasks/{task_id}/reopen", response_model=TaskOut)
def reopen_task(
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_api_user),
    _csrf: None = Depends(verify_csrf_header),
):
    """Le retour du toggle. Sert aussi de « Rétablir » sur une tâche annulée :
    décocher et rétablir, c'est la même transition vers `todo`."""
    task = _get_or_404(db, task_id)
    return _one(db, _set_state(db, task, TASK_TODO, user), user)


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_api_admin),
    _csrf: None = Depends(verify_csrf_header),
):
    """Supprimer efface l'historique de la tâche ; annuler le garde. D'où la
    réserve aux admins — et l'existence de l'état `cancelled` à côté."""
    task_service.delete_task(db, _get_or_404(db, task_id))
