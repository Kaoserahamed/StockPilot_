"""Unit tests for the smallest service modules.

The suite drives these helpers directly against the in-memory session instead of
through the HTTP API so the guard clauses (and the audit truncation rule, which
is only reachable with payloads too large to type in a request) are exercised
explicitly.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.inventory import AuditLog, InventoryTransaction
from app.models.product import Product
from app.services.audit import write_audit
from app.services.inventory_service import apply_stock_change

BUSINESS_ID = 1


# --------------------------------------------------------------------------- #
# app.services.audit
# --------------------------------------------------------------------------- #
class TestWriteAudit:
    """FR-27: append-only trail with values capped to keep the table bounded."""

    def _entries(self, db: Session) -> list[AuditLog]:
        # The session runs with autoflush disabled, so pending rows are not yet
        # visible to a query - flush explicitly, exactly as a request would.
        db.flush()
        return db.query(AuditLog).all()

    def test_persists_every_field(self, db_session: Session) -> None:
        write_audit(
            db_session,
            business_id=BUSINESS_ID,
            user_id=7,
            action="sale.create",
            resource="sale",
            resource_id="42",
            old_value="draft",
            new_value="confirmed",
        )

        entries = self._entries(db_session)
        assert len(entries) == 1
        entry = entries[0]
        assert entry.action == "sale.create"
        assert entry.resource == "sale"
        assert entry.resource_id == "42"
        assert entry.old_value == "draft"
        assert entry.new_value == "confirmed"
        assert entry.business_id == BUSINESS_ID
        assert entry.user_id == 7

    def test_allows_a_system_action_without_a_user(self, db_session: Session) -> None:
        """A null user_id marks an automated change rather than a person's."""
        write_audit(
            db_session,
            business_id=BUSINESS_ID,
            user_id=None,
            action="nightly.close",
            resource="day",
        )

        entry = self._entries(db_session)[0]
        assert entry.user_id is None
        assert entry.resource_id is None

    def test_truncates_an_oversized_old_value(self, db_session: Session) -> None:
        """old_value is capped at 2000 chars so one row cannot bloat the table."""
        payload = "o" * 5000
        write_audit(
            db_session,
            business_id=BUSINESS_ID,
            user_id=1,
            action="product.price_change",
            resource="product",
            old_value=payload,
        )

        stored = self._entries(db_session)[0].old_value
        assert stored is not None
        assert len(stored) == len("o" * 2000) + len("...(truncated)")
        assert stored.endswith("...(truncated)")
        assert stored.startswith("o" * 100)

    def test_truncates_an_oversized_new_value(self, db_session: Session) -> None:
        """new_value is capped by the same rule as old_value."""
        payload = "n" * 4000
        write_audit(
            db_session,
            business_id=BUSINESS_ID,
            user_id=1,
            action="product.price_change",
            resource="product",
            new_value=payload,
        )

        stored = self._entries(db_session)[0].new_value
        assert stored is not None
        assert len(stored) == len("n" * 2000) + len("...(truncated)")
        assert stored.endswith("...(truncated)")

    def test_leaves_a_boundary_length_value_untouched(self, db_session: Session) -> None:
        """Exactly 2000 chars must NOT be truncated - the check is strictly >."""
        payload = "x" * 2000
        write_audit(
            db_session,
            business_id=BUSINESS_ID,
            user_id=1,
            action="product.price_change",
            resource="product",
            old_value=payload,
            new_value=payload,
        )

        entry = self._entries(db_session)[0]
        assert entry.old_value == payload
        assert entry.new_value == payload
        assert "truncated" not in (entry.old_value or "")

    def test_appends_a_second_entry_rather_than_replacing(self, db_session: Session) -> None:
        """The trail is append-only: repeated calls accumulate rows."""
        for index in range(3):
            write_audit(
                db_session,
                business_id=BUSINESS_ID,
                user_id=1,
                action="inventory.adjust",
                resource="product",
                resource_id=str(index),
            )

        assert len(self._entries(db_session)) == 3


# --------------------------------------------------------------------------- #
# app.services.inventory_service
# --------------------------------------------------------------------------- #
def _seed_product(db: Session, *, business_id: int = BUSINESS_ID, quantity: int = 10) -> Product:
    product = Product(
        business_id=business_id,
        name="Widget",
        sku="WID-001",
        quantity_on_hand=quantity,
    )
    db.add(product)
    db.flush()
    return product


class TestApplyStockChange:
    """FR-8: quantity_on_hand has exactly one writer, and it validates first."""

    def test_applies_the_change_and_records_a_transaction(self, db_session: Session) -> None:
        product = _seed_product(db_session)

        updated, tx = apply_stock_change(
            db_session,
            business_id=BUSINESS_ID,
            product_id=product.id,
            quantity_change=-3,
            tx_type="sale",
            reason="sold over the counter",
            user_id=5,
            related_id="S-1",
        )

        assert updated.quantity_on_hand == 7
        assert tx.quantity_change == -3
        assert tx.tx_type == "sale"
        assert tx.reason == "sold over the counter"
        assert tx.related_id == "S-1"

        stored = db_session.query(InventoryTransaction).one()
        assert stored.product_id == product.id

    def test_requires_a_reason(self, db_session: Session) -> None:
        """FR-8: an adjustment with no reason is rejected before any write."""
        product = _seed_product(db_session)

        with pytest.raises(HTTPException) as excinfo:
            apply_stock_change(
                db_session,
                business_id=BUSINESS_ID,
                product_id=product.id,
                quantity_change=5,
                tx_type="adjustment",
                reason="",
                user_id=1,
            )

        assert excinfo.value.status_code == 422
        assert excinfo.value.detail == "Reason is required"
        assert not db_session.query(InventoryTransaction).all()
        assert db_session.query(Product).one().quantity_on_hand == 10

    def test_rejects_a_zero_change(self, db_session: Session) -> None:
        """A no-op transaction is rejected instead of writing an empty ledger row."""
        product = _seed_product(db_session)

        with pytest.raises(HTTPException) as excinfo:
            apply_stock_change(
                db_session,
                business_id=BUSINESS_ID,
                product_id=product.id,
                quantity_change=0,
                tx_type="adjustment",
                reason="nothing changed",
                user_id=1,
            )

        assert excinfo.value.status_code == 422
        assert "zero" in str(excinfo.value.detail)
        assert not db_session.query(InventoryTransaction).all()

    def test_rejects_an_unknown_product(self, db_session: Session) -> None:
        """A missing product is a 404, not a silent no-op."""
        with pytest.raises(HTTPException) as excinfo:
            apply_stock_change(
                db_session,
                business_id=BUSINESS_ID,
                product_id=999,
                quantity_change=1,
                tx_type="adjustment",
                reason="ghost product",
                user_id=1,
            )

        assert excinfo.value.status_code == 404
        assert excinfo.value.detail == "Product not found"

    def test_does_not_leak_a_product_across_tenants(self, db_session: Session) -> None:
        """The lookup is tenant-scoped: another business's product is a 404."""
        product = _seed_product(db_session, business_id=BUSINESS_ID)

        with pytest.raises(HTTPException) as excinfo:
            apply_stock_change(
                db_session,
                business_id=BUSINESS_ID + 1,
                product_id=product.id,
                quantity_change=1,
                tx_type="adjustment",
                reason="wrong tenant",
                user_id=1,
            )

        assert excinfo.value.status_code == 404

    def test_blocks_a_sale_that_would_go_negative(self, db_session: Session) -> None:
        """Stock may not dip below zero on a movement other than an adjustment."""
        product = _seed_product(db_session, quantity=2)

        with pytest.raises(HTTPException) as excinfo:
            apply_stock_change(
                db_session,
                business_id=BUSINESS_ID,
                product_id=product.id,
                quantity_change=-5,
                tx_type="sale",
                reason="oversell",
                user_id=1,
            )

        assert excinfo.value.status_code == 400
        assert "negative" in str(excinfo.value.detail)
        assert db_session.query(Product).one().quantity_on_hand == 2

    def test_allows_an_adjustment_to_record_a_shrinkage_shortfall(
        self, db_session: Session
    ) -> None:
        """An adjustment is the deliberate exception: it may go negative."""
        product = _seed_product(db_session, quantity=2)

        updated, tx = apply_stock_change(
            db_session,
            business_id=BUSINESS_ID,
            product_id=product.id,
            quantity_change=-5,
            tx_type="adjustment",
            reason="shrinkage found on recount",
            user_id=1,
        )

        assert updated.quantity_on_hand == -3
        assert tx.tx_type == "adjustment"

    def test_allows_landing_on_exactly_zero(self, db_session: Session) -> None:
        """Selling the last unit is legal - only below zero is blocked."""
        product = _seed_product(db_session, quantity=4)

        updated, _ = apply_stock_change(
            db_session,
            business_id=BUSINESS_ID,
            product_id=product.id,
            quantity_change=-4,
            tx_type="sale",
            reason="final unit",
            user_id=1,
        )

        assert updated.quantity_on_hand == 0
