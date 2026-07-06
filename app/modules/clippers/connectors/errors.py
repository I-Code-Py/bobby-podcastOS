class ConnectorError(Exception):
    """Erreur générique d'un connecteur de vues."""


class RateLimitedError(ConnectorError):
    """La plateforme limite ou bloque temporairement nos requêtes."""


class ParsingError(ConnectorError):
    """La page a été récupérée mais son format a changé / est illisible."""


class NotFoundError(ConnectorError):
    """La vidéo n'existe pas ou n'est plus publique."""
