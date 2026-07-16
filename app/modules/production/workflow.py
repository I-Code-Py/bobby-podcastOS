"""Les règles de production du studio.

Ce fichier rassemble ce que le prototype éparpillait entre `STEP_TASKS`, la map
`submitLink` et la constante `DELAIS` — c'est-à-dire le métier lui-même, qui n'a
rien à faire dans un navigateur : un client peut être rechargé, contourné ou
modifié, ces règles décident de qui travaille et sous quel délai.
"""

from app.modules.production.models import (
    EP_ROLE_DERUSH,
    EP_ROLE_MINIATURE,
    EP_ROLE_MONTAGE_INTRO,
    EP_ROLE_MONTAGE_PODCAST,
    EP_ROLE_MONTEUR_COURT,
    PHASE_BOOKING,
    PHASE_ETALONNAGE,
    PHASE_MINIATURE_DERUSH,
    PHASE_MONTAGES,
    PHASE_PUBLICATION,
    PHASE_TOURNAGE,
    RESOURCE_AUDIO,
    RESOURCE_AUTRE,
    RESOURCE_MASTER,
    RESOURCE_MINIATURE,
    RESOURCE_MONTAGE,
    RESOURCE_RUSH,
)

# ---------------------------------------------------------------------------
# Les tâches instanciées à la création d'un épisode (STEP_TASKS du prototype)
# ---------------------------------------------------------------------------
# Le prototype rattachait chaque tâche à un PRÉNOM en dur (« Bobby », « Adrien »,
# « Sofia »). On garde le rôle, pas la personne : c'est l'affectation de
# l'épisode (EpisodeAssignment) qui désigne l'humain, sinon changer de monteur
# obligerait à réécrire le code.
#
# `role` vaut None quand la tâche revient au pilote de l'émission (le créateur
# de l'épisode) : le prototype les attribuait toutes à « Bobby ».
PRODUCTION_TEMPLATE: list[tuple[str, str, str | None]] = [
    # (phase, libellé, rôle responsable)
    (PHASE_BOOKING, "Contacter l’invité", None),
    (PHASE_BOOKING, "Caler la date de tournage", None),
    (PHASE_BOOKING, "Préparer le fil d’interview", None),
    (PHASE_TOURNAGE, "Préparer le plateau", EP_ROLE_DERUSH),
    (PHASE_TOURNAGE, "Tourner l’épisode", EP_ROLE_DERUSH),
    (PHASE_TOURNAGE, "Sauvegarder les rushs", EP_ROLE_DERUSH),
    (PHASE_ETALONNAGE, "Étalonner l’image", EP_ROLE_DERUSH),
    (PHASE_ETALONNAGE, "Traiter le son", EP_ROLE_DERUSH),
    (PHASE_MONTAGES, "Montage intro", EP_ROLE_MONTAGE_INTRO),
    (PHASE_MONTAGES, "Montage podcast", EP_ROLE_MONTAGE_PODCAST),
    (PHASE_MONTAGES, "Format court (monteur court)", EP_ROLE_MONTEUR_COURT),
    (PHASE_MINIATURE_DERUSH, "Miniature 16:9", EP_ROLE_MINIATURE),
    (PHASE_MINIATURE_DERUSH, "Dérush clipping", EP_ROLE_DERUSH),
    (PHASE_PUBLICATION, "Titre & description", None),
    (PHASE_PUBLICATION, "Programmer la publication", None),
]

# Le prototype annonçait « 11 tâches de production » dans son assistant de
# création, et affichait « 5 / 11 tâches » sur chaque carte. Le template en
# compte 15 : le chiffre était faux des deux côtés. On le dérive désormais.
PRODUCTION_TASK_COUNT = len(PRODUCTION_TEMPLATE)


# ---------------------------------------------------------------------------
# Délais par défaut, en jours (constante DELAIS du prototype)
# ---------------------------------------------------------------------------
# Rangés dans app_settings pour être réglables depuis l'écran Administration,
# où le prototype affichait des champs qui ne sauvegardaient rien.
SETTING_DELAI_FEEDBACK = "delai_feedback_days"
SETTING_DELAI_MONTAGE = "delai_montage_days"
SETTING_DELAI_MINIATURE = "delai_miniature_days"
SETTING_DELAI_DERUSH = "delai_derush_days"

DEFAULT_DELAIS = {
    SETTING_DELAI_FEEDBACK: 2,
    SETTING_DELAI_MONTAGE: 3,
    SETTING_DELAI_MINIATURE: 2,
    SETTING_DELAI_DERUSH: 2,
}


class ResourceRule:
    """Ce qu'un livrable déclenche : une tâche, pour un rôle, sous un délai."""

    def __init__(self, task_label: str, role: str | None, delay_setting: str):
        self.task_label = task_label
        self.role = role
        self.delay_setting = delay_setting


# Déposer un livrable crée la tâche du maillon suivant de la chaîne :
# un rush ou un audio traité déclenche le travail du monteur ; un montage ou une
# miniature déclenche une validation par le pilote (role=None).
#
# `{title}` est remplacé par le titre du livrable.
RESOURCE_RULES: dict[str, ResourceRule] = {
    RESOURCE_MONTAGE: ResourceRule("Feedback montage — {title}", None, SETTING_DELAI_FEEDBACK),
    RESOURCE_RUSH: ResourceRule(
        "Monter à partir de : {title}", EP_ROLE_MONTAGE_PODCAST, SETTING_DELAI_MONTAGE
    ),
    RESOURCE_AUDIO: ResourceRule(
        "Intégrer l’audio traité — {title}", EP_ROLE_MONTAGE_PODCAST, SETTING_DELAI_MONTAGE
    ),
    RESOURCE_MINIATURE: ResourceRule(
        "Valider la miniature — {title}", None, SETTING_DELAI_MINIATURE
    ),
    # Le prototype ne générait aucune tâche de dérush : DELAIS.derush existait
    # mais n'était jamais utilisé, alors que le dérush est une phase du pipeline.
    RESOURCE_MASTER: ResourceRule(
        "Dérusher pour le clipping — {title}", EP_ROLE_DERUSH, SETTING_DELAI_DERUSH
    ),
    RESOURCE_AUTRE: ResourceRule("Consulter — {title}", None, SETTING_DELAI_FEEDBACK),
}
