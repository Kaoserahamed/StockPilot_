"""Unit tests for the authorization service.

Verifies role-based access control helpers correctly enforce permissions and
raise 403 Forbidden when unauthorized. This module replaces duplicate inline
``_check_write`` functions that previously lived in purchases.py, products.py,
and parties.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.services.authorization import (
    can_manage_business,
    can_manage_employees,
    can_write,
    require_owner,
    require_role,
    require_write_access,
    require_write_or_cashier,
)

if TYPE_CHECKING:
    from app.core.deps import Context


@pytest.fixture
def owner_context() -> Context:
    """Mock context for an Owner."""
    ctx = MagicMock()
    ctx.role = "Owner"
    ctx.business_id = 100
    ctx.user.id = 1
    return ctx


@pytest.fixture
def manager_context() -> Context:
    """Mock context for a Manager."""
    ctx = MagicMock()
    ctx.role = "Manager"
    ctx.business_id = 100
    ctx.user.id = 2
    return ctx


@pytest.fixture
def cashier_context() -> Context:
    """Mock context for a Cashier."""
    ctx = MagicMock()
    ctx.role = "Cashier"
    ctx.business_id = 100
    ctx.user.id = 3
    return ctx


class TestRequireRole:
    """Tests for the generic require_role helper."""

    def test_allows_when_role_matches(self, owner_context: Context) -> None:
        """No exception when role is in allowed list."""
        require_role(owner_context, "Owner", "Manager")  # Should not raise

    def test_allows_single_role(self, manager_context: Context) -> None:
        """Works with a single allowed role."""
        require_role(manager_context, "Manager")  # Should not raise

    def test_denies_when_role_not_allowed(self, cashier_context: Context) -> None:
        """Raises 403 when role is not in allowed list."""
        with pytest.raises(HTTPException) as exc_info:
            require_role(cashier_context, "Owner", "Manager")

        assert exc_info.value.status_code == 403
        assert "Insufficient permissions" in exc_info.value.detail
        assert "Owner" in exc_info.value.detail
        assert "Manager" in exc_info.value.detail

    def test_denies_unknown_role(self) -> None:
        """Raises 403 for unrecognized roles."""
        ctx = MagicMock()
        ctx.role = "SuperUser"  # Not a valid role in the system

        with pytest.raises(HTTPException) as exc_info:
            require_role(ctx, "Owner")

        assert exc_info.value.status_code == 403


class TestRequireOwner:
    """Tests for the require_owner shorthand."""

    def test_allows_owner(self, owner_context: Context) -> None:
        """Owner can pass the check."""
        require_owner(owner_context)  # Should not raise

    def test_denies_manager(self, manager_context: Context) -> None:
        """Manager is denied."""
        with pytest.raises(HTTPException) as exc_info:
            require_owner(manager_context)

        assert exc_info.value.status_code == 403

    def test_denies_cashier(self, cashier_context: Context) -> None:
        """Cashier is denied."""
        with pytest.raises(HTTPException) as exc_info:
            require_owner(cashier_context)

        assert exc_info.value.status_code == 403


class TestRequireWriteAccess:
    """Tests for the standard write permission (Owner/Manager)."""

    def test_allows_owner(self, owner_context: Context) -> None:
        """Owner can write."""
        require_write_access(owner_context)  # Should not raise

    def test_allows_manager(self, manager_context: Context) -> None:
        """Manager can write."""
        require_write_access(manager_context)  # Should not raise

    def test_denies_cashier(self, cashier_context: Context) -> None:
        """Cashier cannot write by default."""
        with pytest.raises(HTTPException) as exc_info:
            require_write_access(cashier_context)

        assert exc_info.value.status_code == 403


class TestRequireWriteOrCashier:
    """Tests for write permission including cashiers (POS/customer mgmt)."""

    def test_allows_owner(self, owner_context: Context) -> None:
        """Owner can write."""
        require_write_or_cashier(owner_context)  # Should not raise

    def test_allows_manager(self, manager_context: Context) -> None:
        """Manager can write."""
        require_write_or_cashier(manager_context)  # Should not raise

    def test_allows_cashier(self, cashier_context: Context) -> None:
        """Cashier can write to parties (suppliers/customers)."""
        require_write_or_cashier(cashier_context)  # Should not raise

    def test_denies_unknown_role(self) -> None:
        """Invalid roles are rejected."""
        ctx = MagicMock()
        ctx.role = "Guest"

        with pytest.raises(HTTPException) as exc_info:
            require_write_or_cashier(ctx)

        assert exc_info.value.status_code == 403


class TestCanWrite:
    """Tests for non-throwing can_write check."""

    def test_owner_can_write(self, owner_context: Context) -> None:
        """Owner has write permission."""
        assert can_write(owner_context) is True

    def test_manager_can_write(self, manager_context: Context) -> None:
        """Manager has write permission."""
        assert can_write(manager_context) is True

    def test_cashier_cannot_write(self, cashier_context: Context) -> None:
        """Cashier does not have general write permission."""
        assert can_write(cashier_context) is False

    def test_unknown_role_cannot_write(self) -> None:
        """Unknown roles return False."""
        ctx = MagicMock()
        ctx.role = "Viewer"
        assert can_write(ctx) is False


class TestCanManageEmployees:
    """Tests for employee management permission (Owner-only)."""

    def test_owner_can_manage(self, owner_context: Context) -> None:
        """Only Owner can manage employees."""
        assert can_manage_employees(owner_context) is True

    def test_manager_cannot_manage(self, manager_context: Context) -> None:
        """Manager cannot manage employees."""
        assert can_manage_employees(manager_context) is False

    def test_cashier_cannot_manage(self, cashier_context: Context) -> None:
        """Cashier cannot manage employees."""
        assert can_manage_employees(cashier_context) is False


class TestCanManageBusiness:
    """Tests for business settings permission (Owner-only)."""

    def test_owner_can_manage_business(self, owner_context: Context) -> None:
        """Owner can update business settings."""
        assert can_manage_business(owner_context) is True

    def test_manager_cannot_manage_business(self, manager_context: Context) -> None:
        """Manager cannot update business settings."""
        assert can_manage_business(manager_context) is False

    def test_cashier_cannot_manage_business(self, cashier_context: Context) -> None:
        """Cashier cannot update business settings."""
        assert can_manage_business(cashier_context) is False


class TestRealWorldScenarios:
    """Integration-style tests simulating actual endpoint usage."""

    def test_product_creation_workflow(
        self, owner_context: Context, manager_context: Context, cashier_context: Context
    ) -> None:
        """Products endpoint: Owner/Manager yes, Cashier no."""
        require_write_access(owner_context)  # OK
        require_write_access(manager_context)  # OK

        with pytest.raises(HTTPException):
            require_write_access(cashier_context)  # Denied

    def test_purchase_workflow(
        self, owner_context: Context, manager_context: Context, cashier_context: Context
    ) -> None:
        """Purchases endpoint: Owner/Manager yes, Cashier no."""
        require_write_access(owner_context)  # OK
        require_write_access(manager_context)  # OK

        with pytest.raises(HTTPException):
            require_write_access(cashier_context)  # Denied

    def test_customer_management_workflow(
        self, owner_context: Context, manager_context: Context, cashier_context: Context
    ) -> None:
        """Parties endpoint: all roles can create customers/suppliers."""
        require_write_or_cashier(owner_context)  # OK
        require_write_or_cashier(manager_context)  # OK
        require_write_or_cashier(cashier_context)  # OK (Cashier needs this for POS)

    def test_employee_invite_workflow(
        self, owner_context: Context, manager_context: Context, cashier_context: Context
    ) -> None:
        """Employee management: Owner-only."""
        require_owner(owner_context)  # OK

        with pytest.raises(HTTPException):
            require_owner(manager_context)  # Denied

        with pytest.raises(HTTPException):
            require_owner(cashier_context)  # Denied

    def test_conditional_ui_rendering(
        self, owner_context: Context, cashier_context: Context
    ) -> None:
        """Non-throwing checks for conditional logic (e.g., showing admin UI)."""
        # Owner sees admin features
        assert can_write(owner_context) is True
        assert can_manage_employees(owner_context) is True
        assert can_manage_business(owner_context) is True

        # Cashier sees read-only/POS-only UI
        assert can_write(cashier_context) is False
        assert can_manage_employees(cashier_context) is False
        assert can_manage_business(cashier_context) is False
