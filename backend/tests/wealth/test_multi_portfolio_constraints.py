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


# ── Downgrade safety (Codex P2 regression) ──────────────────────────


async def test_downgrade_pre_check_refuses_on_multi_active():
    """The migration 0201 downgrade pre-check must refuse multi-active state.

    Codex Auto Review (PR #474) flagged that the downgrade body
    re-creates the legacy ``uq_model_portfolios_org_profile_active``
    partial unique on ``status IN ('draft','backtesting','live')`` —
    but the post-0201 system now allows multiple non-live rows per
    ``(organization_id, profile)``. Re-creating that index after
    duplicates accumulate would raise a duplicate-key error and leave
    rollback halfway applied (the new constraints already dropped,
    the legacy one missing). The downgrade was therefore unusable in
    exactly the scenario the upgrade enables.

    The fix is a pre-check that raises ``RuntimeError`` listing the
    offending pair before any structural change happens. Operator
    must consciously archive the duplicates before retrying.

    This test exercises the same SQL the migration uses, against
    seeded multi-active state, and asserts the pre-check returns the
    expected diagnostic row.
    """
    pre_check_sql = text(
        """
        SELECT organization_id, profile, COUNT(*) AS dup
        FROM model_portfolios
        WHERE status IN ('draft', 'backtesting', 'live')
        GROUP BY 1, 2
        HAVING COUNT(*) > 1
        ORDER BY dup DESC
        LIMIT 1
        """
    )

    # Seed two drafts for the same (org, profile) — exactly the
    # multi-active state that the post-0201 system permits but the
    # legacy unique cannot tolerate.
    async with async_session_factory() as db:
        await _set_org(db, _ORG_A)
        await _insert_portfolio(
            db, org_id=_ORG_A, profile="growth",
            display_name="Multi A", state="draft", status="draft",
        )
        await _insert_portfolio(
            db, org_id=_ORG_A, profile="growth",
            display_name="Multi B", state="draft", status="draft",
        )
        await db.commit()

    # Pre-check fires — operator sees a structured row.
    async with async_session_factory() as db:
        await _set_org(db, _ORG_A)
        result = (await db.execute(pre_check_sql)).fetchone()
    assert result is not None, (
        "Pre-check missed the seeded multi-active state — downgrade "
        "would silently corrupt rollback by recreating a unique index "
        "on top of duplicates."
    )
    assert result[0] == _ORG_A
    assert result[1] == "growth"
    assert result[2] == 2

    # Cleanup: archive one, pre-check now passes (no duplicates).
    async with async_session_factory() as db:
        await _set_org(db, _ORG_A)
        await db.execute(
            text(
                "UPDATE model_portfolios SET status='archived', "
                "state='archived' WHERE display_name = 'Multi B' "
                "AND created_by = 'be4-test'"
            )
        )
        await db.commit()

    async with async_session_factory() as db:
        await _set_org(db, _ORG_A)
        result_after = (await db.execute(pre_check_sql)).fetchone()
    assert result_after is None, (
        "After archiving the duplicate, the pre-check should return "
        "no rows so the downgrade can proceed."
    )


async def test_downgrade_pre_check_passes_on_clean_state():
    """Empty / single-active DB — pre-check returns no rows, downgrade safe.

    On a fresh dev DB or a tenant with no multi-portfolio state, the
    pre-check must allow the downgrade through so CI can roll the
    migration forward and back without manual cleanup. Pins the
    no-op-on-clean contract.
    """
    pre_check_sql = text(
        """
        SELECT organization_id, profile, COUNT(*) AS dup
        FROM model_portfolios
        WHERE status IN ('draft', 'backtesting', 'live')
        GROUP BY 1, 2
        HAVING COUNT(*) > 1
        LIMIT 1
        """
    )

    # Single draft — not a duplicate.
    async with async_session_factory() as db:
        await _set_org(db, _ORG_A)
        await _insert_portfolio(
            db, org_id=_ORG_A, profile="growth",
            display_name="Solo", state="draft", status="draft",
        )
        await db.commit()

    async with async_session_factory() as db:
        await _set_org(db, _ORG_A)
        result = (await db.execute(pre_check_sql)).fetchone()
    assert result is None, (
        "Single draft per (org, profile) should not trigger the "
        "pre-check — only multi-active state must refuse downgrade."
    )
