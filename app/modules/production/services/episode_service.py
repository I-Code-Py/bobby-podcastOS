"""Le cycle de vie d'un épisode : création, avancement, livrables, archivage.

Ce service porte les décisions que le prototype laissait au navigateur — ou ne
prenait pas du tout :

  - le NUMÉRO d'épisode venait d'un compteur client (`epn`), que deux onglets
    ouverts faisaient collider en silence ; il est ici attribué par le serveur
    et garanti unique par la base ;
  - l'AVANCEMENT n'existait pas : le prototype affichait un `idx` que rien
    n'incrémentait, si bien qu'un épisode restait éternellement en booking ;
  - le POURCENTAGE était une constante par phase (5 / 45 / 70 / 100) sans aucun
    rapport avec le travail réellement fait — cocher les 15 tâches ne le
    bougeait pas d'un point ;
  - l'ATTRIBUTION des tâches était un prénom en dur (« Bobby », « Sofia ») ;
    elle se résout ici via l'affectation de l'épisode, seule à savoir qui monte
    CET épisode-là.
"""

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.auth.models import User
from app.core.settings_service import get_setting
from app.modules.production.models import (
    EPISODE_ROLES,
    ORIGIN_RESOURCE,
    ORIGIN_TEMPLATE,
    PHASE_BOOKING,
    PHASES,
    RESOURCE_KINDS,
    TASK_CANCELLED,
    TASK_DONE,
    TASK_TODO,
    Episode,
    EpisodeAssignment,
    EpisodeResource,
    Task,
)
from app.modules.production.workflow import (
    DEFAULT_DELAIS,
    PRODUCTION_TEMPLATE,
    RESOURCE_RULES,
)

# Deux créations simultanées visent le même `number` ; l'index unique en
# recale une seule, qui retente avec le numéro suivant. Une poignée d'essais
# suffit : au-delà, ce n'est plus de la contention mais une panne.
_NUMBER_ATTEMPTS = 5


def _episode_load_options():
    """Tout ce qu'une carte d'épisode affiche, chargé d'avance.

    Sans cela, lister 30 épisodes déclenche 90 requêtes : la liste lit les
    tâches (progression), les ressources (compteur) et les affectations
    (« Qui gère quoi ») de chacun.
    """
    return (
        selectinload(Episode.tasks),
        selectinload(Episode.resources),
        selectinload(Episode.assignments),
    )


# ---------------------------------------------------------------------------
# Affectations
# ---------------------------------------------------------------------------


def _validate_assignments(db: Session, assignments: dict[str, int]) -> dict[str, int]:
    """Refuse un rôle inconnu ou un membre inexistant.

    Le prototype affichait la constante globale EP_ROLES, jamais reliée à un
    épisode ni à un compte : n'importe quelle chaîne y passait.
    """
    validated: dict[str, int] = {}
    for role, member_id in (assignments or {}).items():
        if role not in EPISODE_ROLES:
            raise ValueError(f"Rôle d'épisode inconnu : « {role} »")
        if member_id is None:
            continue
        if db.get(User, member_id) is None:
            raise ValueError(f"Le membre #{member_id} n'existe pas")
        validated[role] = member_id
    return validated


def _assignment_map(episode: Episode) -> dict[str, int]:
    return {a.role: a.member_id for a in episode.assignments}


def _resolve_assignee(role: str | None, roles: dict[str, int], pilot_id: int | None) -> int | None:
    """À qui revient une tâche : au titulaire du rôle sur CET épisode, sinon au
    pilote.

    Un rôle non pourvu ne doit pas produire une tâche orpheline que personne ne
    verra dans « Mes tâches » — elle retombe sur le pilote, qui réaffectera.
    """
    if role is None:
        return pilot_id
    return roles.get(role) or pilot_id


def set_assignments(db: Session, episode: Episode, assignments: dict[str, int]) -> Episode:
    """Pose ou remplace les titulaires des rôles fournis sur cet épisode.

    Sémantique partielle : un rôle absent de la requête n'est pas touché, un
    rôle à None est libéré. Les tâches déjà instanciées ne sont pas réaffectées
    — qui a la tâche en main la garde tant qu'un humain n'en décide pas
    autrement.
    """
    validated = _validate_assignments(db, assignments)
    existing = {a.role: a for a in episode.assignments}

    for role, member_id in (assignments or {}).items():
        current = existing.get(role)
        if role not in validated:  # valeur nulle : le poste est libéré
            if current is not None:
                episode.assignments.remove(current)
            continue
        if current is None:
            episode.assignments.append(
                EpisodeAssignment(role=role, member_id=validated[role])
            )
        else:
            current.member_id = validated[role]

    db.commit()
    db.refresh(episode)
    return episode


# ---------------------------------------------------------------------------
# Création
# ---------------------------------------------------------------------------


def _next_number(db: Session) -> int:
    return int(db.scalar(select(func.max(Episode.number))) or 0) + 1


def _instantiate_template(episode: Episode, roles: dict[str, int], pilot_id: int | None) -> None:
    """Déroule les 15 tâches du template sur l'épisode.

    La position est comptée PAR PHASE : c'est l'ordre de la checklist affichée
    dans l'étape, pas un rang global.
    """
    positions: dict[str, int] = {}
    for phase, label, role in PRODUCTION_TEMPLATE:
        position = positions.get(phase, 0)
        positions[phase] = position + 1
        episode.tasks.append(
            Task(
                phase=phase,
                position=position,
                label=label,
                state=TASK_TODO,
                origin=ORIGIN_TEMPLATE,
                assignee_id=_resolve_assignee(role, roles, pilot_id),
            )
        )


def create_episode(
    db: Session,
    guest: str,
    created_by: User,
    shoot_date: date | None = None,
    publish_date: date | None = None,
    assignments: dict[str, int] | None = None,
) -> Episode:
    """Crée un épisode en booking, avec ses affectations et ses 15 tâches.

    Le créateur est le pilote de l'émission : il hérite des tâches dont le
    template ne désigne pas de rôle, et de celles dont le rôle n'est pas
    pourvu.
    """
    guest = (guest or "").strip()
    if not guest:
        raise ValueError("Le nom de l'invité est obligatoire")

    roles = _validate_assignments(db, assignments or {})
    pilot_id = created_by.id

    for _ in range(_NUMBER_ATTEMPTS):
        episode = Episode(
            number=_next_number(db),
            guest=guest,
            phase=PHASE_BOOKING,
            shoot_date=shoot_date,
            publish_date=publish_date,
            created_by_id=pilot_id,
        )
        for role, member_id in roles.items():
            episode.assignments.append(EpisodeAssignment(role=role, member_id=member_id))
        _instantiate_template(episode, roles, pilot_id)

        db.add(episode)
        try:
            db.commit()
        except IntegrityError:
            # Un autre créateur a pris le numéro entre le SELECT max et le
            # COMMIT : on rejoue avec le suivant.
            db.rollback()
            continue
        db.refresh(episode)
        return episode

    raise RuntimeError("Impossible d'attribuer un numéro d'épisode : réessayez")


# ---------------------------------------------------------------------------
# Lecture
# ---------------------------------------------------------------------------


def list_episodes(db: Session, archived: bool = False) -> list[Episode]:
    """Les épisodes actifs (ou les archivés), du plus récent au plus ancien."""
    return list(
        db.scalars(
            select(Episode)
            .where(Episode.archived == archived)
            .order_by(Episode.number.desc())
            .options(*_episode_load_options())
        )
    )


def get_episode(db: Session, episode_id: int) -> Episode | None:
    return db.scalar(
        select(Episode).where(Episode.id == episode_id).options(*_episode_load_options())
    )


# ---------------------------------------------------------------------------
# Mise à jour
# ---------------------------------------------------------------------------


def update_episode(
    db: Session,
    episode: Episode,
    guest: str | None = None,
    publish_date: date | None = None,
    shoot_date: date | None = None,
) -> Episode:
    """Modifie les champs fournis. `None` signifie « inchangé ».

    Les dates s'effacent donc via set_publish_date/set_shoot_date plutôt qu'en
    passant None ici, faute de pouvoir distinguer « absent » de « à vider » sur
    une signature de service.
    """
    if guest is not None:
        guest = guest.strip()
        if not guest:
            raise ValueError("Le nom de l'invité est obligatoire")
        episode.guest = guest
    if publish_date is not None:
        episode.publish_date = publish_date
    if shoot_date is not None:
        episode.shoot_date = shoot_date
    db.commit()
    db.refresh(episode)
    return episode


def set_phase(db: Session, episode: Episode, phase: str) -> Episode:
    """Place l'épisode sur une phase du pipeline.

    On autorise le retour en arrière : un tournage raté renvoie l'épisode en
    booking, et refuser ce mouvement obligerait à supprimer l'épisode pour le
    recréer (avec un numéro de plus).
    """
    if phase not in PHASES:
        raise ValueError(f"Phase inconnue : « {phase} »")
    episode.phase = phase
    db.commit()
    db.refresh(episode)
    return episode


def advance_phase(db: Session, episode: Episode, phase: str | None = None) -> Episode:
    """Avance l'épisode : sur la phase demandée, ou sur la suivante par défaut.

    Le prototype n'avait aucun mécanisme d'avancement — l'index de phase était
    lu mais jamais écrit. Arrivé en publication, on n'avance plus : la suite
    d'un épisode publié, c'est l'archivage.
    """
    if phase is not None:
        return set_phase(db, episode, phase)
    next_index = min(episode.phase_index + 1, len(PHASES) - 1)
    return set_phase(db, episode, PHASES[next_index])


def set_archived(db: Session, episode: Episode, archived: bool) -> Episode:
    episode.archived = archived
    db.commit()
    db.refresh(episode)
    return episode


def archive(db: Session, episode: Episode) -> Episode:
    return set_archived(db, episode, True)


def unarchive(db: Session, episode: Episode) -> Episode:
    return set_archived(db, episode, False)


def delete_episode(db: Session, episode: Episode) -> None:
    """Supprime l'épisode ; tâches, ressources et affectations suivent par
    cascade déclarée sur les relations."""
    db.delete(episode)
    db.commit()


# ---------------------------------------------------------------------------
# Livrables
# ---------------------------------------------------------------------------


def _delay_days(db: Session, setting_key: str) -> int:
    """Le délai réglé dans l'Administration, sinon celui du studio.

    Un réglage illisible (champ vidé à la main en base) ne doit pas empêcher de
    déposer un livrable : on retombe sur la valeur par défaut.
    """
    default = DEFAULT_DELAIS[setting_key]
    raw = get_setting(db, setting_key)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def add_resource(
    db: Session,
    episode: Episode,
    kind: str,
    title: str,
    url: str,
    created_by: User,
) -> tuple[EpisodeResource, Task]:
    """Dépose un livrable et engendre la tâche du maillon suivant.

    C'est la règle métier centrale du studio : un rush déposé met le monteur au
    travail, un montage déposé appelle un feedback. Le prototype affichait bien
    un formulaire de dépôt, mais la tâche générée était figée au 2026-07-17 et
    n'était reliée ni au livrable ni à personne.
    """
    if kind not in RESOURCE_KINDS:
        raise ValueError(f"Type de livrable inconnu : « {kind} »")
    title = (title or "").strip()
    if not title:
        raise ValueError("Le titre du livrable est obligatoire")
    url = (url or "").strip()
    if not url:
        raise ValueError("Le lien du livrable est obligatoire")

    resource = EpisodeResource(
        kind=kind,
        title=title,
        url=url,
        created_by_id=created_by.id,
    )
    # On passe par les collections de l'épisode plutôt que d'écrire les clés
    # étrangères en direct : sinon l'épisode déjà chargé en session garderait
    # ses anciennes listes, et le livrage tout juste déposé serait invisible
    # jusqu'à la requête suivante (progression comprise).
    episode.resources.append(resource)
    # La tâche référence la ressource : il faut son id avant de la construire.
    db.flush()

    rule = RESOURCE_RULES[kind]
    pilot_id = episode.created_by_id or created_by.id
    task = Task(
        label=rule.task_label.format(title=title),
        state=TASK_TODO,
        origin=ORIGIN_RESOURCE,
        # Pas de phase : la tâche naît d'un dépôt, pas d'une étape du pipeline.
        due_date=date.today() + timedelta(days=_delay_days(db, rule.delay_setting)),
        assignee_id=_resolve_assignee(rule.role, _assignment_map(episode), pilot_id),
        resource_id=resource.id,
    )
    episode.tasks.append(task)
    db.commit()
    db.refresh(resource)
    db.refresh(task)
    return resource, task


def list_resources(db: Session, episode: Episode) -> list[EpisodeResource]:
    return sorted(episode.resources, key=lambda r: r.id, reverse=True)


# ---------------------------------------------------------------------------
# Progression
# ---------------------------------------------------------------------------


def progress(db: Session, episode: Episode) -> dict:
    """Avancement réel : part des tâches faites parmi celles qui restent dues.

    Le prototype affichait un pourcentage constant par phase (5 / 45 / 70 / 100)
    et un « 5 / 11 tâches » écrit en dur, alors que le template en compte 15.
    Ici les deux sortent des tâches elles-mêmes.

    Les tâches annulées sortent du dénominateur : une étape abandonnée ne doit
    pas plafonner à jamais la progression sous 100 %.
    """
    counted = [t for t in episode.tasks if t.state != TASK_CANCELLED]
    done = sum(1 for t in counted if t.state == TASK_DONE)
    total = len(counted)
    return {
        "percent": round(done * 100 / total) if total else 0,
        "task_count": total,
        "done_count": done,
    }
