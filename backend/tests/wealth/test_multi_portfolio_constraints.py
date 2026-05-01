"""PR-BE-4 — multi-portfolio constraint redesign.

Verifies the migration 0201 partial unique index
``uq_model_portfolios_primary_live`` and the per-org UNIQUE
``uq_model_portfolios_org_display_name`` against a live PostgreSQL.

Layout of this suite:

1. ``test_multi_drafts_per_profile_succeed`` — three drafts +
   constructed/validated/approved variants for the same
   ``(org, profile=growth)`` all coexist.
2. ``test_single_live_per_profile_enforced`` — a single
   ``state='live'`` row inserts; the second is rejected by
   ``uq_model_portfolios_primary_live``.
3. ``test_duplicate_display_name_within_org_rejected`` — two
   portfolios with the same ``display_name`` in the same org
   collide on ``uq_model_portfolios_org_display_name``.
4. ``test_duplicate_display_name_cross_org_allowed`` — same
   ``display_name`` in two different orgs is fine; RLS isolates
   each tenant and the unique key carries ``organization_id``.

Convention: ``growth`` is the canonical post-Q165 profile (the
``aggressive`` legacy alias was removed in migration 0199). Tests
seed and tear down their own rows with deterministic UUIDs so
they are safely re-runnable.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.db.engine import async_session_factory

# Deterministic test UUIDs — be4 prefix so they cannot conflict with
# real tenants or other test suites.
_ORG_A = uuid.UUID("0be40000-0000-0000-0000-000000000001")
_ORG_B = uuid.UUID("0be40000-0000-0000-0000-000000000002")

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def _set_org(db, org_id: uuid.UUID) -> None:
    await db.execute(
        text("SELECT set_config('app.current_organization_id', :oid, true)"),
        {"oid": str(org_id)},
    )


async def _insert_portfolio(
    db,
    *,
    org_id: uuid.UUID,
    profile: str,
    display_name: str,
    state: str,
    status: str = "draft",
) -> uuid.UUID:
    """Insert a model_portfolios row directly via SQL.

    Bypasses the ORM so the test focuses on the DB-level constraints;
    we want the partial unique to fire on raw INSERT, not at any
    application validation layer.
    """
    pid = uuid.uuid4()
    await db.execute(
        text(
            """
            INSERT INTO model_portfolios (
                id, organization_id, profile, display_name,
                status, state, state_metadata, inception_nav, created_by
            ) VALUES (
                :id, :oid, :profile, :name,
                :status, :state, '{}'::jsonb, 1000.0, 'be4-test'
            )
            """
        ),
        {
            "id": pid,
            "oid": org_id,
            "profile": profile,
            "name": display_name,
            "status": status,
            "state": state,
        },
    )
    return pid


@pytest.fixture(autouse=True)
async def _cleanup_be4_rows():
    """Drop any rows left from a previous run before and after each test."""
    async with async_session_factory() as db:
        for org in (_ORG_A, _ORG_B):
            await _set_org(db, org)
            await db.execute(
                text("DELETE FROM model_portfolios WHERE created_by = 'be4-test'")
            )
        await db.commit()
    yield
    async with async_session_factory() as db:
        for org in (_ORG_A, _ORG_B):
            await _set_org(db, org)
            await db.execute(
                text("DELETE FROM model_portfolios WHERE created_by = 'be4-test'")
            )
        await db.commit()


async def test_multi_drafts_per_profile_succeed():
    """Multiple non-live portfolios per (org, profile) must coexist.

    The migration 0201 partial unique only constrains ``state='live'``;
    every earlier lifecycle stage may have arbitrarily many rows so
    the user can stage several candidate portfolios at once.
    """
    async with async_session_factory() as db:
        await _set_org(db, _ORG_A)
        await _insert_portfolio(
            db, org_id=_ORG_A, profile="growth",
            display_name="Growth A", state="draft",
        )
        await _insert_portfolio(
            db, org_id=_ORG_A, profile="growth",
            display_name="Growth B", state="draft",
        )
        await _insert_portfolio(
            db, org_id=_ORG_A, profile="growth",
            display_name="Growth C", state="draft",
        )
        await _insert_portfolio(
            db, org_id=_ORG_A, profile="growth",
            display_name="Growth D", state="constructed",
        )
        await _insert_portfolio(
            db, org_id=_ORG_A, profile="growth",
            display_name="Growth E", state="validated",
        )
        await _insert_portfolio(
            db, org_id=_ORG_A, profile="growth",
            display_name="Growth F", state="approved",
        )
        await db.commit()

        count = (
            await db.execute(
                text(
                    "SELECT COUNT(*) FROM model_portfolios "
                    "WHERE organization_id = :oid AND profile = 'growth'"
                ),
                {"oid": _ORG_A},
            )
        ).scalar_one()
    assert count == 6


async def test_single_live_per_profile_enforced():
    """``state='live'`` is unique per (organization_id, profile).

    asyncpg raises ``UniqueViolationError`` on the INSERT itself
    (not deferred to commit) because the partial unique index is
    immediate. Both the second INSERT and the subsequent
    rollback recovery are exercised here.
    """
    async with async_session_factory() as db:
        await _set_org(db, _ORG_A)
        await _insert_portfolio(
            db, org_id=_ORG_A, profile="growth",
            display_name="Growth Live 1", state="live", status="live",
        )
        await db.commit()

    async with async_session_factory() as db:
        await _set_org(db, _ORG_A)
        with pytest.raises(IntegrityError) as excinfo:
            await _insert_portfolio(
                db, org_id=_ORG_A, profile="growth",
                display_name="Growth Live 2", state="live", status="live",
            )
        assert "uq_model_portfolios_primary_live" in str(excinfo.value)
        await db.rollback()


async def test_duplicate_display_name_within_org_rejected():
    """``(organization_id, display_name)`` must be unique per tenant."""
    async with async_session_factory() as db:
        await _set_org(db, _ORG_A)
        await _insert_portfolio(
            db, org_id=_ORG_A, profile="growth",
            display_name="Identical Name", state="draft",
        )
        await db.commit()

    async with async_session_factory() as db:
        await _set_org(db, _ORG_A)
        with pytest.raises(IntegrityError) as excinfo:
            await _insert_portfolio(
                db, org_id=_ORG_A, profile="moderate",
                display_name="Identical Name", state="draft",
            )
        assert "uq_model_portfolios_org_display_name" in str(excinfo.value)
        await db.rollback()


async def test_duplicate_display_name_cross_org_allowed():
    """Two tenants may use the same ``display_name``.

    The unique key is composite ``(organization_id, display_name)``;
    cross-org duplicates are allowed because the index carries
    ``organization_id`` as the leading column. This is the
    institutional norm — every family office can have its own
    "Core Growth" portfolio. RLS enforces tenant isolation at the
    routes layer; this test asserts only the index semantics
    because the dev ``netz`` role is a superuser and bypasses RLS.
    """
    async with async_session_factory() as db:
        await _set_org(db, _ORG_A)
        await _insert_portfolio(
            db, org_id=_ORG_A, profile="growth",
            display_name="Core Growth", state="draft",
        )
        await db.commit()

    async with async_session_factory() as db:
        await _set_org(db, _ORG_B)
        await _insert_portfolio(
            db, org_id=_ORG_B, profile="growth",
            display_name="Core Growth", state="draft",
        )
        await db.commit()

    async with async_session_factory() as db:
        for org in (_ORG_A, _ORG_B):
            await _set_org(db, org)
            count = (
                await db.execute(
                    text(
                        "SELECT COUNT(*) FROM model_portfolios "
                        "WHERE display_name = 'Core Growth' "
                        "AND organization_id = :oid"
                    ),
                    {"oid": org},
                )
            ).scalar_one()
            assert count == 1, (
                f"Expected exactly one 'Core Growth' for org {org}, got {count}"
            )
