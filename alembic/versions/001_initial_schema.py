"""initial schema

Revision ID: 001_initial
Revises:
Create Date: 2025-01-01 00:00:00

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("username", sa.String(100), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(512), nullable=False),
        sa.Column("role", sa.String(50), nullable=False, server_default="viewer"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "clippers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("notes", sa.Text),
        sa.Column("active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("clipper_id", sa.Integer, sa.ForeignKey("clippers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", sa.Enum("youtube", "tiktok", "instagram", name="platform"), nullable=False),
        sa.Column("profile_url", sa.String(512), nullable=False, unique=True),
        sa.Column("handle", sa.String(255), nullable=False),
        sa.Column("status", sa.Enum("active", "manual_required", "error", name="accountstatus"), nullable=False, server_default="active"),
        sa.Column("last_fetch_at", sa.DateTime),
        sa.Column("consecutive_failures", sa.Integer, nullable=False, server_default="0"),
        sa.Column("views_at_last_payout_checkpoint", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "account_videos",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform_video_id", sa.String(255), nullable=False),
        sa.Column("url", sa.String(512), nullable=False),
        sa.Column("title", sa.Text),
        sa.Column("view_count", sa.BigInteger),
        sa.Column("duration_seconds", sa.Integer),
        sa.Column("published_at", sa.Date),
        sa.Column("last_seen_at", sa.Date),
        sa.UniqueConstraint("account_id", "platform_video_id", name="uq_account_video"),
    )

    op.create_table(
        "account_video_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("account_video_id", sa.Integer, sa.ForeignKey("account_videos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("view_count", sa.BigInteger, nullable=False),
        sa.Column("captured_at", sa.Date, nullable=False),
        sa.UniqueConstraint("account_video_id", "captured_at", name="uq_video_snapshot"),
    )

    op.create_table(
        "account_view_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("total_views", sa.BigInteger, nullable=False),
        sa.Column("video_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("captured_at", sa.Date, nullable=False),
        sa.UniqueConstraint("account_id", "captured_at", name="uq_account_view_snapshot"),
    )

    op.create_table(
        "payout_cycles",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("period_start", sa.Date, nullable=False),
        sa.Column("period_end", sa.Date, nullable=False),
        sa.Column("total_cents", sa.Integer, nullable=False, server_default="0"),
        sa.Column("paid_at", sa.DateTime),
    )

    op.create_table(
        "payout_lines",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("cycle_id", sa.Integer, sa.ForeignKey("payout_cycles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("clipper_id", sa.Integer, sa.ForeignKey("clippers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("clipper_name_snapshot", sa.String(255), nullable=False),
        sa.Column("total_cents", sa.Integer, nullable=False, server_default="0"),
        sa.Column("paid_at", sa.DateTime),
    )

    op.create_table(
        "payout_line_account_details",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("line_id", sa.Integer, sa.ForeignKey("payout_lines.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("handle_snapshot", sa.String(255), nullable=False),
        sa.Column("platform_snapshot", sa.String(50), nullable=False),
        sa.Column("delta_views", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("payout_cents", sa.Integer, nullable=False, server_default="0"),
    )

    op.create_table(
        "payout_line_account_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("detail_id", sa.Integer, sa.ForeignKey("payout_line_account_details.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("start_views", sa.BigInteger, nullable=False),
        sa.Column("end_views", sa.BigInteger, nullable=False),
    )

    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
    op.drop_table("payout_line_account_snapshots")
    op.drop_table("payout_line_account_details")
    op.drop_table("payout_lines")
    op.drop_table("payout_cycles")
    op.drop_table("account_view_snapshots")
    op.drop_table("account_video_snapshots")
    op.drop_table("account_videos")
    op.drop_table("accounts")
    op.drop_table("clippers")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS platform")
    op.execute("DROP TYPE IF EXISTS accountstatus")
