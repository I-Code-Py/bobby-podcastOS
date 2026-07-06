from datetime import date

import pytest
from sqlalchemy import select

from app.modules.clippers.models import (
    Account,
    AccountVideo,
    AccountVideoSnapshot,
    AccountViewSnapshot,
    Clipper,
)
from app.modules.clippers.services import (
    account_service,
    clipper_service,
    payout_service,
)


def _clipper_with_account(db, name: str, views: int = 5000) -> Account:
    clipper = Clipper(name=name)
    db.add(clipper)
    db.flush()
    account = Account(clipper_id=clipper.id, platform="youtube",
                      profile_url=f"https://youtube.com/@{name}")
    db.add(account)
    db.flush()
    video = AccountVideo(account_id=account.id, platform_video_id="v1",
                        view_count=views)
    db.add(video)
    db.flush()
    db.add(AccountVideoSnapshot(account_video_id=video.id, view_count=views,
                                captured_at=date.today()))
    db.add(AccountViewSnapshot(account_id=account.id, total_views=views,
                               video_count=1, captured_at=date.today()))
    db.commit()
    return account


class TestReassignAccount:
    def test_moves_account_to_new_clipper(self, db):
        account = _clipper_with_account(db, "Momo")
        other = Clipper(name="Crlly")
        db.add(other)
        db.commit()

        account_service.reassign_account(db, account, other)
        assert account.clipper_id == other.id

    def test_reassigning_to_same_clipper_raises(self, db):
        account = _clipper_with_account(db, "Momo")
        same = db.get(Clipper, account.clipper_id)
        with pytest.raises(ValueError):
            account_service.reassign_account(db, account, same)


class TestDeleteAccount:
    def test_deletes_account_and_its_history(self, db):
        account = _clipper_with_account(db, "Momo")
        account_id = account.id

        account_service.delete_account(db, account)

        assert db.get(Account, account_id) is None
        assert db.scalar(select(AccountVideo).where(
            AccountVideo.account_id == account_id)) is None
        assert db.scalar(select(AccountViewSnapshot).where(
            AccountViewSnapshot.account_id == account_id)) is None

    def test_refuses_to_delete_account_already_in_a_payout(self, db):
        account = _clipper_with_account(db, "Momo")
        payout_service.generate_cycle(db)  # crée un PayoutLineAccountSnapshot

        with pytest.raises(ValueError):
            account_service.delete_account(db, account)
        # toujours là
        assert db.get(Account, account.id) is not None


class TestDeleteClipper:
    def test_deletes_clipper_and_its_accounts(self, db):
        account = _clipper_with_account(db, "Momo")
        clipper_id = account.clipper_id
        clipper = clipper_service.get_clipper(db, clipper_id)

        clipper_service.delete_clipper(db, clipper)

        assert clipper_service.get_clipper(db, clipper_id) is None
        assert db.get(Account, account.id) is None

    def test_refuses_to_delete_clipper_with_paid_account(self, db):
        account = _clipper_with_account(db, "Momo")
        clipper_id = account.clipper_id
        payout_service.generate_cycle(db)
        clipper = clipper_service.get_clipper(db, clipper_id)

        with pytest.raises(ValueError):
            clipper_service.delete_clipper(db, clipper)
        assert clipper_service.get_clipper(db, clipper_id) is not None
