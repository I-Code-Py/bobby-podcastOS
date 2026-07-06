from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

PLATFORM_YOUTUBE = "youtube"
PLATFORM_TIKTOK = "tiktok"
PLATFORM_INSTAGRAM = "instagram"
PLATFORMS = (PLATFORM_YOUTUBE, PLATFORM_TIKTOK, PLATFORM_INSTAGRAM)

PLATFORM_LABELS = {
    PLATFORM_YOUTUBE: "YouTube",
    PLATFORM_TIKTOK: "TikTok",
    PLATFORM_INSTAGRAM: "Instagram",
}

# Statuts d'un compte vis-à-vis de la collecte automatique des vues
ACCOUNT_STATUS_ACTIVE = "active"
ACCOUNT_STATUS_MANUAL_REQUIRED = "manual_required"
ACCOUNT_STATUS_ERROR = "error"
ACCOUNT_STATUS_ARCHIVED = "archived"

PAYOUT_PENDING = "pending"
PAYOUT_PAID = "paid"
PAYOUT_SUPERSEDED = "superseded"

SNAPSHOT_SOURCE_AUTO = "auto"
SNAPSHOT_SOURCE_MANUAL = "manual"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Clipper(Base):
    __tablename__ = "clippers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    notes: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    accounts: Mapped[list["Account"]] = relationship(back_populates="clipper")


class Account(Base):
    """Un compte réseau social (une chaîne/profil sur une plateforme) assigné
    à un clippeur. On scrape toutes ses vidéos et on somme leurs vues."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    clipper_id: Mapped[int] = mapped_column(ForeignKey("clippers.id"), index=True)
    platform: Mapped[str] = mapped_column(String(20))
    profile_url: Mapped[str] = mapped_column(String(700), unique=True)
    handle: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default=ACCOUNT_STATUS_ACTIVE)
    last_fetch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_fetch_status: Mapped[str | None] = mapped_column(String(30))
    last_fetch_error: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    # Vues déjà rémunérées : figées uniquement quand un récap est marqué payé
    views_at_last_payout_checkpoint: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    clipper: Mapped[Clipper] = relationship(back_populates="accounts")
    videos: Mapped[list["AccountVideo"]] = relationship(back_populates="account")
    snapshots: Mapped[list["AccountViewSnapshot"]] = relationship(
        back_populates="account", order_by="AccountViewSnapshot.captured_at"
    )

    @property
    def latest_total_views(self) -> int:
        return self.snapshots[-1].total_views if self.snapshots else 0

    @property
    def latest_video_count(self) -> int:
        return self.snapshots[-1].video_count if self.snapshots else 0

    @property
    def platform_label(self) -> str:
        return PLATFORM_LABELS.get(self.platform, self.platform)


class AccountVideo(Base):
    """Une vidéo trouvée sur le compte lors d'un scraping (upsert par id)."""

    __tablename__ = "account_videos"
    __table_args__ = (UniqueConstraint("account_id", "platform_video_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    platform_video_id: Mapped[str] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(String(700))
    title: Mapped[str | None] = mapped_column(Text)
    view_count: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    published_at: Mapped[date | None] = mapped_column(Date)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    account: Mapped[Account] = relationship(back_populates="videos")
    snapshots: Mapped[list["AccountVideoSnapshot"]] = relationship(
        back_populates="video", order_by="AccountVideoSnapshot.captured_at"
    )


class AccountVideoSnapshot(Base):
    """Nombre de vues d'une vidéo à une date (historique jour par jour, pour
    suivre l'évolution de chaque vidéo)."""

    __tablename__ = "account_video_snapshots"
    __table_args__ = (UniqueConstraint("account_video_id", "captured_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_video_id: Mapped[int] = mapped_column(
        ForeignKey("account_videos.id"), index=True
    )
    view_count: Mapped[int] = mapped_column(Integer)
    captured_at: Mapped[date] = mapped_column(Date)

    video: Mapped[AccountVideo] = relationship(back_populates="snapshots")


class AccountViewSnapshot(Base):
    """Total des vues du compte (somme de toutes ses vidéos) à une date."""

    __tablename__ = "account_view_snapshots"
    __table_args__ = (UniqueConstraint("account_id", "captured_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    total_views: Mapped[int] = mapped_column(Integer)
    video_count: Mapped[int] = mapped_column(Integer, default=0)
    captured_at: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(10), default=SNAPSHOT_SOURCE_AUTO)

    account: Mapped[Account] = relationship(back_populates="snapshots")


class PayoutCycle(Base):
    __tablename__ = "payout_cycles"

    id: Mapped[int] = mapped_column(primary_key=True)
    week_start_date: Mapped[date] = mapped_column(Date)
    week_end_date: Mapped[date] = mapped_column(Date)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    lines: Mapped[list["PayoutLine"]] = relationship(back_populates="cycle")


class PayoutLine(Base):
    __tablename__ = "payout_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    payout_cycle_id: Mapped[int] = mapped_column(ForeignKey("payout_cycles.id"), index=True)
    clipper_id: Mapped[int] = mapped_column(ForeignKey("clippers.id"), index=True)
    delta_views: Mapped[int] = mapped_column(Integer)
    amount_due_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default=PAYOUT_PENDING)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_by_line_id: Mapped[int | None] = mapped_column(ForeignKey("payout_lines.id"))

    cycle: Mapped[PayoutCycle] = relationship(back_populates="lines")
    clipper: Mapped[Clipper] = relationship()
    account_details: Mapped[list["PayoutLineAccountDetail"]] = relationship(
        back_populates="line"
    )
    account_snapshots: Mapped[list["PayoutLineAccountSnapshot"]] = relationship(
        back_populates="line"
    )


class PayoutLineAccountDetail(Base):
    __tablename__ = "payout_line_account_details"

    id: Mapped[int] = mapped_column(primary_key=True)
    payout_line_id: Mapped[int] = mapped_column(ForeignKey("payout_lines.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    delta_views: Mapped[int] = mapped_column(Integer)
    amount_cents: Mapped[int] = mapped_column(Integer)

    line: Mapped[PayoutLine] = relationship(back_populates="account_details")
    account: Mapped[Account] = relationship()


class PayoutLineAccountSnapshot(Base):
    """Fige les vues début/fin par compte pour ce récap (base du checkpoint)."""

    __tablename__ = "payout_line_account_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    payout_line_id: Mapped[int] = mapped_column(ForeignKey("payout_lines.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    start_views: Mapped[int] = mapped_column(Integer)
    end_views: Mapped[int] = mapped_column(Integer)
    delta_views: Mapped[int] = mapped_column(Integer)

    line: Mapped[PayoutLine] = relationship(back_populates="account_snapshots")
    account: Mapped[Account] = relationship()


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(String(500))
