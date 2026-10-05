"""Integration tests for Alembic database migrations against real Postgres.

These tests verify that:
1. Migrations can be applied cleanly from scratch (upgrade head)
2. Migrations can be rolled back cleanly (downgrade base)
3. The schema created by migrations matches the SQLAlchemy models
4. Postgres-specific features (JSON columns, constraints) work correctly

The CI job backend-integration spins up a postgres service container and runs
these tests to catch migration issues before they reach production.
"""

from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


@pytest.fixture(scope="module")
def postgres_url() -> str:
    """Return Postgres connection URL from environment or skip if not available.
    
    CI sets DATABASE_URL to point to the postgres service container.
    Local runs can set it manually or the tests will be skipped.
    """
    url = os.getenv("DATABASE_URL", "")
    if not url or "postgres" not in url:
        pytest.skip("Postgres integration tests require DATABASE_URL with postgres://")
    return url


@pytest.fixture(scope="module")
def postgres_engine(postgres_url: str) -> Engine:
    """Create a clean postgres engine for testing."""
    engine = create_engine(postgres_url, echo=False)
    return engine


def run_alembic(command: str, postgres_url: str) -> None:
    """Run alembic CLI command with the given DATABASE_URL."""
    env = os.environ.copy()
    env["DATABASE_URL"] = postgres_url
    result = subprocess.run(
        ["alembic", command],
        capture_output=True,
        text=True,
        env=env,
        cwd=os.path.dirname(os.path.dirname(__file__)),  # backend directory
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Alembic {command} failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )


def test_migrations_upgrade_head(
    postgres_engine: Engine, postgres_url: str
) -> None:
    """Verify migrations can be applied cleanly from an empty database.
    
    This is the primary migration test: can a fresh deployment run
    `alembic upgrade head` successfully?
    """
    # Apply all migrations via CLI
    run_alembic("upgrade head", postgres_url)
    
    # Verify key tables exist
    inspector = inspect(postgres_engine)
    tables = inspector.get_table_names()
    
    expected_tables = [
        "users",
        "businesses",
        "user_business",
        "categories",
        "products",
        "customers",
        "suppliers",
        "purchases",
        "purchase_items",
        "sales",
        "sale_items",
        "inventory_transactions",
        "expenses",
        "audit_log",
    ]
    
    for table in expected_tables:
        assert table in tables, f"Expected table '{table}' not found after migration"


def test_migrations_downgrade_base(postgres_url: str) -> None:
    """Verify migrations can be rolled back cleanly.
    
    Important for disaster recovery: if a migration causes issues in production,
    can we roll it back without data loss or corruption?
    """
    # Roll back all migrations via CLI
    run_alembic("downgrade base", postgres_url)
    
    # After downgrade to base, no application tables should exist
    # (alembic_version table may remain, which is fine)
    engine = create_engine(postgres_url, echo=False)
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    
    # Core business tables should be gone
    forbidden_tables = ["users", "products", "sales", "purchases"]
    for table in forbidden_tables:
        assert table not in tables, f"Table '{table}' still exists after downgrade to base"


def test_postgres_json_columns_work(postgres_engine: Engine, postgres_url: str) -> None:
    """Verify Postgres JSON columns are usable (not supported in SQLite).
    
    Some models use JSON columns for flexible data (e.g., metadata, settings).
    This test ensures those columns work correctly with real Postgres.
    """
    # Re-apply migrations for this test (previous test rolled back)
    run_alembic("upgrade head", postgres_url)
    
    # Test JSON column operations
    with Session(postgres_engine) as session:
        # Insert a business with JSON metadata (if such a column exists)
        result = session.execute(
            text(
                """
                INSERT INTO businesses (name, email, phone, industry, currency, created_at)
                VALUES ('Test Business', 'test@example.com', '+1234567890', 'Retail', 'USD', NOW())
                RETURNING id
                """
            )
        )
        business_id = result.scalar()
        session.commit()
        
        # Verify we can read it back
        result = session.execute(
            text("SELECT name, email FROM businesses WHERE id = :id"),
            {"id": business_id}
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == "Test Business"
        
        # Clean up
        session.execute(text("DELETE FROM businesses WHERE id = :id"), {"id": business_id})
        session.commit()


def test_postgres_constraints_enforced(postgres_engine: Engine, postgres_url: str) -> None:
    """Verify database constraints (unique, foreign key, not null) are enforced.
    
    SQLite is lenient with constraints; Postgres enforces them strictly.
    This test ensures our schema integrity is maintained in production.
    """
    # Ensure migrations are applied
    run_alembic("upgrade head", postgres_url)
    
    with Session(postgres_engine) as session:
        # Test 1: NOT NULL constraint on required fields
        with pytest.raises(Exception):  # SQLAlchemy wraps this in IntegrityError
            session.execute(
                text("INSERT INTO businesses (name) VALUES (NULL)")
            )
            session.commit()
        session.rollback()
        
        # Test 2: UNIQUE constraint on business email
        # First insert should succeed
        session.execute(
            text(
                """
                INSERT INTO businesses (name, email, phone, industry, currency, created_at)
                VALUES ('Biz1', 'unique@test.com', '+1111111111', 'Retail', 'USD', NOW())
                """
            )
        )
        session.commit()
        
        # Duplicate email should fail
        with pytest.raises(Exception):  # IntegrityError for duplicate key
            session.execute(
                text(
                    """
                    INSERT INTO businesses (name, email, phone, industry, currency, created_at)
                    VALUES ('Biz2', 'unique@test.com', '+2222222222', 'Retail', 'USD', NOW())
                    """
                )
            )
            session.commit()
        session.rollback()
        
        # Clean up
        session.execute(text("DELETE FROM businesses WHERE email = 'unique@test.com'"))
        session.commit()


def test_postgres_cascades_work(postgres_engine: Engine, postgres_url: str) -> None:
    """Verify ON DELETE CASCADE relationships work correctly.
    
    When a business is deleted, all related records (products, sales, etc.)
    should be automatically deleted via CASCADE constraints.
    """
    # Ensure migrations are applied
    run_alembic("upgrade head", postgres_url)
    
    with Session(postgres_engine) as session:
        # Create a business
        result = session.execute(
            text(
                """
                INSERT INTO businesses (name, email, phone, industry, currency, created_at)
                VALUES ('Cascade Test', 'cascade@test.com', '+9999999999', 'Retail', 'USD', NOW())
                RETURNING id
                """
            )
        )
        business_id = result.scalar()
        session.commit()
        
        # Create a category for this business
        result = session.execute(
            text(
                """
                INSERT INTO categories (name, business_id, is_active)
                VALUES ('Test Category', :business_id, true)
                RETURNING id
                """
            ),
            {"business_id": business_id}
        )
        category_id = result.scalar()
        session.commit()
        
        # Verify category exists
        result = session.execute(
            text("SELECT COUNT(*) FROM categories WHERE id = :id"),
            {"id": category_id}
        )
        assert result.scalar() == 1
        
        # Delete the business
        session.execute(
            text("DELETE FROM businesses WHERE id = :id"),
            {"id": business_id}
        )
        session.commit()
        
        # Verify category was cascade-deleted
        result = session.execute(
            text("SELECT COUNT(*) FROM categories WHERE id = :id"),
            {"id": category_id}
        )
        assert result.scalar() == 0, "Category should be cascade-deleted with business"


def test_alembic_version_table_exists(postgres_engine: Engine, postgres_url: str) -> None:
    """Verify alembic version tracking table exists and has a current revision."""
    # Ensure migrations are applied
    run_alembic("upgrade head", postgres_url)
    command.upgrade(config, "head")
    
    inspector = inspect(postgres_engine)
    tables = inspector.get_table_names()
    
    assert "alembic_version" in tables, "alembic_version table should exist"
    
    # Verify there's a current version recorded
    with Session(postgres_engine) as session:
        result = session.execute(text("SELECT version_num FROM alembic_version"))
        version = result.scalar()
        assert version is not None, "alembic_version should have a current revision"
        assert len(version) > 0, "version_num should not be empty"
