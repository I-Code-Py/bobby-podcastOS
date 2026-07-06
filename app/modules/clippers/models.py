from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, Enum, ForeignKey,
    Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class AccountStatus(str, enum.Enum):
    active = "active"
    manual_required = "manual_required"
    error = "error"


class Platform(str, enum.Enum):
    youtube = "youtube"
    tiktok = "tiktok"
    instagram = "instagram"


class Clipper(Base):
    __tablename__ = "clippers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    payment_link: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    accounts: Mapped[list[Account]] = relationship(
        "Account", back_populates="clipper", cascade="all, delete-orphan"
    )
    payout_lines: Mapped[list[PayoutLine]] = relationship(
        "PayoutLine", back_populates="clipper"
    )


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    clipper_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("clippers.id", ondelete="CASCADE"), nullable=False
    )
    platform: Mapped[Platform] = mapped_column(Enum(Platform), nullable=False)
    profile_url: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    handle: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[AccountStatus] = mapped_column(
        Enum(AccountStatus), default=AccountStatus.active, nullable=False
    )
    last_fetch_at: Mapped[datetime | None] = mapped_column(DateTime)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    views_at_last_payout_checkpoint: Mapped[int] = mapped_column(
        BigInteger, default=0, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    clipper: Mapped[Clipper] = relationship("Clipper", back_populates="accounts")
    videos: Mapped[list[AccountVideo]] = relationship(
        "AccountVideo", back_populates="account", cascade="all, delete-orphan"
    )
    view_snapshots: Mapped[list[AccountViewSnapshot]] = relationship(
        "AccountViewSnapshot", back_populates="account", cascade="all, delete-orphan"
    )

    @property
    def latest_total_views(self) -> int:
        if not self.view_snapshots:
            return 0
        return max(s.total_views for s in self.view_snapshots)


class AccountVideo(Base):
    __tablename__ = "account_videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    platform_video_id: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    view_count: Mapped[int | None] = mapped_column(BigInteger)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    published_at: Mapped[date | None] = mapped_column(Date)
    last_seen_at: Mapped[date | None] = mapped_column(Date)

    __table_args__ = (UniqueConstraint("account_id", "platform_video_id"),)

    account: Mapped[Account] = relationship("Account", back_populates="videos")
    snapshots: Mapped[list[AccountVideoSnapshot]] = relationship(
        "AccountVideoSnapshot", back_populates="video", cascade="all, delete-orphan"
    )


class AccountVideoSnapshot(Base):
    __tablename__ = "account_video_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_video_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("account_videos.id", ondelete="CASCADE"), nullable=False
    )
    view_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    captured_at: Mapped[date] = mapped_column(Date, nullable=False)

    __table_args__ = (UniqueConstraint("account_video_id", "captured_at"),)

    video: Mapped[AccountVideo] = relationship("AccountVideo", back_populates="snapshots")


class AccountViewSnapshot(Base):
    __tablename__ = "account_view_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    total_views: Mapped[int] = mapped_column(BigInteger, nullable=False)
    video_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    captured_at: Mapped[date] = mapped_column(Date, nullable=False)

    __table_args__ = (UniqueConstraint("account_id", "captured_at"),)

    account: Mapped[Account] = relationship("Account", back_populates="view_snapshots")


class PayoutCycle(Base):
    __tablename__ = "payout_cycles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    total_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime)

    lines: Mapped[list[PayoutLine]] = relationship(
        "PayoutLine", back_populates="cycle", cascade="all, delete-orphan"
    )


class PayoutLine(Base):
    __tablename__ = "payout_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cycle_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("payout_cycles.id", ondelete="CASCADE"), nullable=False
    )
    clipper_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("clippers.id", ondelete="SET NULL"), nullable=True
    )
    clipper_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    total_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime)
    held: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    hold_note: Mapped[str | None] = mapped_column(Text)

    cycle: Mapped[PayoutCycle] = relationship("PayoutCycle", back_populates="lines")
    clipper: Mapped[Clipper | None] = relationship("Clipper", back_populates="payout_lines")
    account_details: Mapped[list[PayoutLineAccountDetail]] = relationship(
        "PayoutLineAccountDetail", back_populates="line", cascade="all, delete-orphan"
    )


class PayoutLineAccountDetail(Base):
    __tablename__ = "payout_line_account_details"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    line_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("payout_lines.id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    handle_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    platform_snapshot: Mapped[str] = mapped_column(String(50), nullable=False)
    delta_views: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    payout_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    line: Mapped[PayoutLine] = relationship("PayoutLine", back_populates="account_details")
    snapshot: Mapped[PayoutLineAccountSnapshot | None] = relationship(
        "PayoutLineAccountSnapshot", back_populates="detail",
        uselist=False, cascade="all, delete-orphan"
    )


class PayoutLineAccountSnapshot(Base):
    __tablename__ = "payout_line_account_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    detail_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("payout_line_account_details.id", ondelete="CASCADE"),
        nullable=False, unique=True
    )
    start_views: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_views: Mapped[int] = mapped_column(BigInteger, nullable=False)

    detail: Mapped[PayoutLineAccountDetail] = relationship(
        "PayoutLineAccountDetail", back_populates="snapshot"
    )


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[str] = mapped_column(String(50), default="viewer", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
