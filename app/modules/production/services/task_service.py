"""Les tâches : les lire, les créer, les cocher, les annuler.

Le prototype tenait l'achèvement dans une map `checked: Record<string, boolean>`
vivant à côté des tâches : non persistante, GLOBALE (cocher chez soi cochait
chez tout le monde) et muette sur qui avait coché et quand. Ici l'état est une
colonne de la tâche, avec sa trace — c'est tout le sens de `set_state`.

Ce module ne renvoie que des dates et des états. Aucun libellé (« sous 3 j »,
« jeudi 17 »), aucune couleur : le prototype figeait ces chaînes en base de son
état, si bien qu'une tâche pour le 17 restait « sous 3 j » le 20.
"""

from datetime import date, datetime, timezone

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session, selectinload

from app.core.auth.models import User
from app.modules.production.models import (
    ORIGIN_MANUAL,
    PHASES,
    TASK_CANCELLED,
    TASK_DONE,
    TASK_STATES,
    TASK_TODO,
    Episode,
    Task,
)

# Une tâche sans épisode est une tâche de clipping (voir le docstring de Task) :
# le prototype exprimait ça par une clé polymorphe `epKey === 'clip'`.
SCOPE_CLIPPING = "clipping"
SCOPE_EPISODES = "episodes"
SCOPES = (SCOPE_CLIPPING, SCOPE_EPISODES)

# Sentinelle des mises à jour partielles : `None` est une valeur légitime
# (« plus d'échéance », « plus d'assigné »), elle ne peut donc pas signifier
# « ne touche pas à ce champ ».
UNSET = object()


def _is_open() -> ColumnElement[bool]:
    """« Ouverte » = ni terminée, ni annulée.

    Écrit en `notin_` plutôt qu'en `== TASK_TODO` : le jour où un état
    intermédiaire apparaît, une tâche en cours doit continuer à peser dans la
    charge de son assigné, pas en disparaître silencieusement.
    """
    return Task.state.notin_((TASK_DONE, TASK_CANCELLED))


def _ordered(stmt):
    """Tri STABLE : l'échéance, les sans-date en dernier, puis l'ancienneté.

    Le prototype n'avait aucun tri secondaire : à date égale, l'ordre des tâches
    changeait d'un rendu à l'autre. `id` clôt le départage, `created_at` étant
    posé par le serveur et donc identique pour deux tâches créées dans la même
    transaction (l'instanciation d'un template, typiquement).

    Les tâches sans échéance passent après : une date connue est une information,
    son absence n'en est pas une, et les faire remonter en tête (ce que fait un
    `ORDER BY` naïf en Postgres, où NULL est « grand », l'inverse en SQLite)
    donnerait deux ordres différents selon la base.
    """
    return stmt.order_by(
        Task.due_date.is_(None),
        Task.due_date,
        Task.created_at,
        Task.id,
    )


def list_tasks(
    db: Session,
    assignee_id: int | None = None,
    episode_id: int | None = None,
    include_done: bool = True,
    scope: str | None = None,
) -> list[Task]:
    """Les tâches, filtrées et triées, épisode préchargé.

    `selectinload` sur l'épisode : chaque tâche affiche le numéro et l'invité de
    son épisode, ce qui sans préchargement fait une requête par ligne.
    """
    stmt = select(Task).options(selectinload(Task.episode))

    if assignee_id is not None:
        stmt = stmt.where(Task.assignee_id == assignee_id)
    if episode_id is not None:
        stmt = stmt.where(Task.episode_id == episode_id)
    if not include_done:
        stmt = stmt.where(Task.state != TASK_DONE)
    if scope == SCOPE_CLIPPING:
        stmt = stmt.where(Task.episode_id.is_(None))
    elif scope == SCOPE_EPISODES:
        stmt = stmt.where(Task.episode_id.is_not(None))

    return list(db.scalars(_ordered(stmt)))


def load_users(db: Session, tasks: list[Task]) -> dict[int, User]:
    """Les humains cités par ce lot de tâches (assignés et cocheurs), en UNE requête.

    `Task.assignee_id` et `Task.completed_by_id` sont de vraies clés étrangères
    mais ne portent pas de relation ORM : les résoudre une par une rendrait le
    préchargement de l'épisode inutile, le N+1 revenant par la porte des noms.
    C'est le pendant serveur du `who` du prototype, qui valait tantôt des
    initiales (« BS »), tantôt un prénom (« Bobby »), et ne se reliait à rien.
    """
    ids = {task.assignee_id for task in tasks} | {task.completed_by_id for task in tasks}
    ids.discard(None)
    if not ids:
        return {}
    return {user.id: user for user in db.scalars(select(User).where(User.id.in_(ids)))}


def get_task(db: Session, task_id: int) -> Task | None:
    return db.scalar(
        select(Task).where(Task.id == task_id).options(selectinload(Task.episode))
    )


def _assert_episode(db: Session, episode_id: int | None) -> None:
    if episode_id is not None and db.get(Episode, episode_id) is None:
        raise ValueError("Cet épisode n'existe pas")


def _assert_assignee(db: Session, assignee_id: int | None) -> None:
    if assignee_id is not None and db.get(User, assignee_id) is None:
        raise ValueError("Ce membre n'existe pas")


def create_task(
    db: Session,
    label: str,
    created_by: User,
    episode_id: int | None = None,
    assignee_id: int | None = None,
    due_date: date | None = None,
    phase: str | None = None,
) -> Task:
    """Une tâche créée à la main (les autres naissent d'un template ou d'un dépôt).

    L'épisode et l'assigné sont vérifiés ici : le prototype reliait ses tâches à
    des chaînes libres, et une faute de frappe donnait une tâche assignée à
    personne, sans que rien ne le signale.
    """
    label = label.strip()
    if not label:
        raise ValueError("Le libellé de la tâche est obligatoire")
    if phase is not None and phase not in PHASES:
        raise ValueError("Phase inconnue")
    _assert_episode(db, episode_id)
    _assert_assignee(db, assignee_id)

    task = Task(
        label=label,
        state=TASK_TODO,
        origin=ORIGIN_MANUAL,
        episode_id=episode_id,
        assignee_id=assignee_id,
        due_date=due_date,
        phase=phase,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def requires_admin(state: str) -> bool:
    """Annuler est un acte d'admin ; cocher ne l'est pas.

    Exposé plutôt que codé en dur dans `set_state` : c'est au routeur de
    connaître l'utilisateur de la session et de répondre 403, le service n'a pas
    à savoir qu'il existe une couche HTTP au-dessus de lui.
    """
    return state == TASK_CANCELLED


def set_state(db: Session, task: Task, state: str, user: User) -> Task:
    """Change l'état d'une tâche et garde la trace de qui l'a fait.

    `completed_at` / `completed_by_id` ne valent que pour une tâche terminée : on
    les efface dès qu'elle ne l'est plus, sinon une tâche rouverte garderait un
    « terminée par Sofia » que plus rien ne justifie.

    Une tâche annulée ne se coche pas — il faut d'abord la rétablir. Le prototype
    ignorait déjà le clic sur une tâche annulée, mais côté affichage seulement :
    la règle appartient au métier, pas au gestionnaire d'événements.
    """
    if state not in TASK_STATES:
        raise ValueError("État de tâche inconnu")
    if task.state == TASK_CANCELLED and state == TASK_DONE:
        raise ValueError("Cette tâche est annulée : rétablis-la avant de la cocher")

    task.state = state
    if state == TASK_DONE:
        task.completed_at = datetime.now(timezone.utc)
        task.completed_by_id = user.id
    else:
        task.completed_at = None
        task.completed_by_id = None

    db.commit()
    db.refresh(task)
    return task


def update_task(
    db: Session,
    task: Task,
    label: str | None = None,
    due_date: date | None | object = UNSET,
    assignee_id: int | None | object = UNSET,
) -> Task:
    """Modifie une tâche, champ par champ.

    `due_date` et `assignee_id` acceptent `None` pour effacer, d'où la sentinelle
    `UNSET` : sans elle, « retirer l'échéance » et « ne pas toucher à l'échéance »
    seraient le même appel, et l'un des deux serait impossible à exprimer.
    """
    if label is not None:
        label = label.strip()
        if not label:
            raise ValueError("Le libellé de la tâche est obligatoire")
        task.label = label
    if due_date is not UNSET:
        task.due_date = due_date
    if assignee_id is not UNSET:
        _assert_assignee(db, assignee_id)
        task.assignee_id = assignee_id

    db.commit()
    db.refresh(task)
    return task


def delete_task(db: Session, task: Task) -> None:
    db.delete(task)
    db.commit()


def open_task_count(db: Session, member_id: int) -> int:
    """La charge d'un membre : ses tâches ni terminées ni annulées.

    C'est le `load` de la vue Équipe, que le prototype écrivait EN DUR et ne
    recalculait jamais — Bobby y affichait « load: 2 » sous trois chips.
    """
    return int(
        db.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.assignee_id == member_id, _is_open())
        )
        or 0
    )


def open_tasks_for(db: Session, member_id: int, limit: int = 5) -> list[Task]:
    """Les tâches ouvertes d'un membre : les « chips » de sa carte Équipe.

    Bornées, car la carte n'en montre que quelques-unes : le compte complet, lui,
    vient de `open_task_count` et ne se déduit pas de la longueur de cette liste.
    """
    stmt = _ordered(
        select(Task)
        .where(Task.assignee_id == member_id, _is_open())
        .options(selectinload(Task.episode))
    )
    return list(db.scalars(stmt.limit(limit)))


def phase_is_cancelled(db: Session, episode_id: int, phase: str) -> bool:
    """Vrai dès qu'UNE tâche de la phase est annulée.

    Règle du prototype conservée telle quelle : une seule tâche annulée marque
    toute l'étape, et cet état prime sur « passée » comme sur « en cours ».
    """
    return db.scalar(
        select(Task.id)
        .where(
            Task.episode_id == episode_id,
            Task.phase == phase,
            Task.state == TASK_CANCELLED,
        )
        .limit(1)
    ) is not None
