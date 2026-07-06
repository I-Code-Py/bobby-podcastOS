import pytest

from app.modules.clippers.models import Clipper
from app.modules.clippers.services import clipper_service, payment_service


class TestNormalizeHandle:
    def test_plain_pseudo(self):
        assert payment_service.normalize_handle("bobby") == "bobby"

    def test_strips_leading_at(self):
        assert payment_service.normalize_handle("@bobby") == "bobby"

    def test_extracts_from_paypal_link(self):
        assert payment_service.normalize_handle(
            "https://paypal.me/bobby") == "bobby"

    def test_extracts_from_revolut_link_with_query(self):
        assert payment_service.normalize_handle(
            "https://revolut.me/bobby?amount=10") == "bobby"

    def test_extracts_from_paypalme_long_form(self):
        assert payment_service.normalize_handle(
            "paypal.com/paypalme/bobby") == "bobby"

    def test_blank_is_empty(self):
        assert payment_service.normalize_handle("   ") == ""


class TestBuildPaymentLink:
    def test_paypal_rounds_integer_amount(self):
        # 5000 cents = 50,00 € → "50" dans l'URL
        assert payment_service.build_payment_link("paypal", "bobby", 5000) == (
            "https://paypal.me/bobby/50EUR"
        )

    def test_paypal_keeps_decimals(self):
        assert payment_service.build_payment_link("paypal", "bobby", 1050) == (
            "https://paypal.me/bobby/10.5EUR"
        )

    def test_revolut_link(self):
        assert payment_service.build_payment_link("revolut", "bobby", 2599) == (
            "https://revolut.me/bobby/25.99eur"
        )

    def test_no_method_returns_none(self):
        assert payment_service.build_payment_link(None, "bobby", 5000) is None

    def test_no_handle_returns_none(self):
        assert payment_service.build_payment_link("paypal", None, 5000) is None

    def test_zero_amount_returns_none(self):
        assert payment_service.build_payment_link("paypal", "bobby", 0) is None


class TestSetPaymentInfo:
    def test_saves_method_and_normalized_handle(self, db):
        clipper = Clipper(name="Momo")
        db.add(clipper)
        db.commit()

        clipper_service.set_payment_info(db, clipper, "paypal",
                                         "https://paypal.me/momo")
        assert clipper.payment_method == "paypal"
        assert clipper.payment_handle == "momo"

    def test_empty_method_clears_payment(self, db):
        clipper = Clipper(name="Momo", payment_method="paypal",
                          payment_handle="momo")
        db.add(clipper)
        db.commit()

        clipper_service.set_payment_info(db, clipper, "", "")
        assert clipper.payment_method is None
        assert clipper.payment_handle is None

    def test_method_without_handle_raises(self, db):
        clipper = Clipper(name="Momo")
        db.add(clipper)
        db.commit()

        with pytest.raises(ValueError):
            clipper_service.set_payment_info(db, clipper, "revolut", "  ")
