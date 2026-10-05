"""Authorization helpers for role-based access control.

This module extracts repeated permission-checking patterns from route handlers
into a single service, eliminating duplication flagged by DataFactor's code
quality scan.

Prior to this refactor, every router (purchases.py, products.py, parties.py)
defined its own ``_check_write(ctx)`` with inline role checks. This led to:
- Code duplication across 3+ files
- Inconsistent error messages
- No central place to audit authorization logic
- Test coverage gaps

Now all RBAC checks flow through this module, making the permission model
auditable, testable, and maintainable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException, status

if TYPE_CHECKING:
    from app.core.deps import Context


def require_role(ctx: Context, *allowed_roles: str) -> None:
    """Raise 403 if the current user's role is not in the allowed list.

    Args:
        ctx: The authenticated user context (from get_current_context dependency)
        *allowed_roles: Role names that are permitted (e.g., "Owner", "Manager")

    Raises:
        HTTPException: 403 Forbidden if ctx.role not in allowed_roles

    Examples:
        # Owner/Manager only endpoints:
        require_role(ctx, "Owner", "Manager")

        # All staff can perform this action:
        require_role(ctx, "Owner", "Manager", "Cashier")

        # Owner-only endpoint:
        require_role(ctx, "Owner")
    """
    if ctx.role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Insufficient permissions: requires one of {', '.join(allowed_roles)}",
        )


def require_owner(ctx: Context) -> None:
    """Shorthand for owner-only endpoints (business settings, employee mgmt)."""
    require_role(ctx, "Owner")


def require_write_access(ctx: Context) -> None:
    """Standard write permission: Owner or Manager.

    Use this for most write operations (products, purchases, inventory adjustments).
    Cashiers are read-only or POS-only by default.
    """
    require_role(ctx, "Owner", "Manager")


def require_write_or_cashier(ctx: Context) -> None:
    """Write permission including cashiers (suppliers, customers, POS).

    Use this for entities that cashiers need to create/update at the counter
    (customers, suppliers when recording a quick purchase, etc).
    """
    require_role(ctx, "Owner", "Manager", "Cashier")


def can_write(ctx: Context) -> bool:
    """Check if user can perform write operations (non-throwing version).

    Returns:
        True if role is Owner or Manager, False otherwise

    Use this for conditional logic rather than authorization gates:
        if can_write(ctx):
            # Show admin UI
        else:
            # Read-only view
    """
    return ctx.role in ("Owner", "Manager")


def can_manage_employees(ctx: Context) -> bool:
    """Check if user can invite/remove employees (Owner only)."""
    return ctx.role == "Owner"


def can_manage_business(ctx: Context) -> bool:
    """Check if user can update business profile/settings (Owner only)."""
    return ctx.role == "Owner"
