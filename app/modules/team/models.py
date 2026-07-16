"""Invitations et traces d'envoi.

Le prototype affichait « Invitation envoyée à Bobby » et une pastille
« Invitation envoyée — en attente », sans rien envoyer : pas de requête, pas de
jeton, pas même un champ pour le contact — le formulaire ne demandait que le
nom, rendant l'invité littéralement injoignable. Et rien ne pouvait faire passer
l'état à « accepté ».
"""

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

INVITE_PENDING = "pending"
INVITE_ACCEPTED = "accepted"
INVITE_REVOKED = "revoked"
INVITE_STATUSES = (INVITE_PENDING, INVITE_ACCEPTED, INVITE_REVOKED)

INVITE_TTL_DAYS = 7


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def default_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=INVITE_TTL_DAYS)


class Invitation(Base):
    """Une invitation à rejoindre le studio, avec jeton à usage unique."""

    __tablename__ = "invitations"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Le compte créé en statut `invited`, que cette invitation doit activer.
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    token: Mapped[str] = mapped_column(String(64), unique=True, index=True, default=generate_token)
    status: Mapped[str] = mapped_column(String(20), default=INVITE_PENDING, index=True)

    # Sur quel canal elle est partie, pour pouvoir relancer au même endroit.
    channel: Mapped[str | None] = mapped_column(String(20), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Une invitation qui échoue à partir reste exploitable (relance), mais on
    # garde pourquoi : un numéro faux se corrige, il ne se devine pas.
    send_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=default_expiry
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    invited_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    @property
    def is_expired(self) -> bool:
        expires = self.expires_at
        # Postgres rend un datetime aware ; SQLite (tests) le rend naïf.
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) > expires

    @property
    def is_usable(self) -> bool:
        return self.status == INVITE_PENDING and not self.is_expired


class Notification(Base):
    """Trace d'un message envoyé à un membre.

    Le prototype ouvrait un lien `wa.me` (l'humain devait encore appuyer sur
    Envoyer) ou un salon Discord public en jetant le message au passage. Aucun
    accusé, aucune trace. On garde ici ce qui est parti, à qui, et si ça a
    abouti — sans quoi « je ne l'ai jamais reçu » est indémontrable.
    """

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(20))
    body: Mapped[str] = mapped_column(Text)

    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    sent_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
