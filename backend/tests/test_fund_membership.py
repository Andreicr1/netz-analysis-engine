"""Tests for AUTH-02: fund membership resolution into Actor.fund_ids.

Covers:
- Actor.fund_ids populated from DB for non-admin actors
- Authorized fund access succeeds, unauthorized fund access denied
- Admin and super-admin bypass fund membership entirely
- Dev header fund_ids override (no DB lookup)
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.core.security.clerk_auth import Actor
from app.shared.enums import Role

# Stable UUIDs for test isolation
FUND_A = "11111111-1111-1111-1111-111111111111"
FUND_B = "22222222-2222-2222-2222-222222222222"
ORG_ID = "00000000-0000-0000-0000-000000000001"

# --- Unit tests for Actor.can_access_fund ---


class TestActorCanAccessFund:
    """Unit tests for the Actor.can_access_fund method."""

    def test_admin_bypasses_fund_check(self):
        """ADMIN bypasses fund_ids — always has access."""
        actor = Actor(
            actor_id="admin-user",
            name="Admin",
            email="admin@netz.capital",
            roles=[Role.ADMIN],
            fund_ids=[],
        )
        assert actor.can_access_fund(uuid.uuid4())

    def test_super_admin_bypasses_fund_check(self):
        """SUPER_ADMIN bypasses fund_ids — always has access."""
        actor = Actor(
            actor_id="super-admin",
            name="Super Admin",
            email="super@netz.capital",
            roles=[Role.SUPER_ADMIN],
            fund_ids=[],
        )
        assert actor.can_access_fund(uuid.uuid4())

    def test_investor_with_membership_can_access(self):
        """INVESTOR with fund_id in fund_ids can access that fund."""
        fund_id = uuid.UUID(FUND_A)
        actor = Actor(
            actor_id="investor-1",
            name="Investor",
            email="investor@acme.com",
            roles=[Role.INVESTOR],
            fund_ids=[fund_id],
        )
        assert actor.can_access_fund(fund_id)

    def test_investor_without_membership_denied(self):
        """INVESTOR without fund_id in fund_ids is denied."""
        fund_a = uuid.UUID(FUND_A)
        fund_b = uuid.UUID(FUND_B)
        actor = Actor(
            actor_id="investor-1",
            name="Investor",
            email="investor@acme.com",
            roles=[Role.INVESTOR],
            fund_ids=[fund_a],
        )
        assert not actor.can_access_fund(fund_b)

    def test_investment_team_with_membership(self):
        """INVESTMENT_TEAM with fund membership can access assigned fund."""
        fund_id = uuid.UUID(FUND_A)
        actor = Actor(
            actor_id="team-1",
            name="Team Member",
            email="team@acme.com",
            roles=[Role.INVESTMENT_TEAM],
            fund_ids=[fund_id],
        )
        assert actor.can_access_fund(fund_id)

    def test_gp_without_membership_denied(self):
        """GP without fund membership is denied."""
        actor = Actor(
            actor_id="gp-1",
            name="GP",
            email="gp@acme.com",
            roles=[Role.GP],
            fund_ids=[],
        )
        assert not actor.can_access_fund(uuid.uuid4())

    def test_empty_fund_ids_non_admin_denied(self):
        """Non-admin with empty fund_ids is denied for any fund."""
        actor = Actor(
            actor_id="user-1",
            name="User",
            email="user@acme.com",
            roles=[Role.COMPLIANCE],
            fund_ids=[],
        )
        assert not actor.can_access_fund(uuid.uuid4())


# --- Integration tests via dev header (no DB required) ---


class TestFundAccessDevHeader:
    """Integration tests using X-DEV-ACTOR header with explicit fund_ids."""

    @pytest.mark.asyncio
    async def test_investor_authorized_fund_succeeds(self, client: AsyncClient):
        """INVESTOR with fund A in dev header can access fund A routes."""
        header = {
            "X-DEV-ACTOR": f'{{"actor_id": "inv-1", "roles": ["INVESTOR"], "fund_ids": ["{FUND_A}"], "org_id": "{ORG_ID}"}}',
        }
        # Use investor portal as representative fund-scoped route
        response = await client.get(
            f"/api/v1/funds/{FUND_A}/investor/report-packs",
            headers=header,
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_investor_unauthorized_fund_denied(self, client: AsyncClient):
        """INVESTOR with fund A in dev header is denied for fund B."""
        header = {
            "X-DEV-ACTOR": f'{{"actor_id": "inv-1", "roles": ["INVESTOR"], "fund_ids": ["{FUND_A}"], "org_id": "{ORG_ID}"}}',
        }
        response = await client.get(
            f"/api/v1/funds/{FUND_B}/investor/report-packs",
            headers=header,
        )
        assert response.status_code == 403
        assert "No access to this fund" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_admin_empty_fund_ids_bypasses(self, client: AsyncClient):
        """ADMIN with empty fund_ids can access any fund."""
        header = {
            "X-DEV-ACTOR": f'{{"actor_id": "admin-1", "roles": ["ADMIN"], "fund_ids": [], "org_id": "{ORG_ID}"}}',
        }
        response = await client.get(
            f"/api/v1/funds/{FUND_A}/investor/report-packs",
            headers=header,
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_super_admin_empty_fund_ids_bypasses(self, client: AsyncClient):
        """SUPER_ADMIN with empty fund_ids can access any fund."""
        header = {
            "X-DEV-ACTOR": f'{{"actor_id": "sa-1", "roles": ["SUPER_ADMIN"], "fund_ids": [], "org_id": "{ORG_ID}"}}',
        }
        response = await client.get(
            f"/api/v1/funds/{FUND_B}/investor/report-packs",
            headers=header,
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_gp_no_fund_ids_denied(self, client: AsyncClient):
        """GP with no fund_ids in dev header is denied (no DB fallback in dev header path)."""
        header = {
            "X-DEV-ACTOR": f'{{"actor_id": "gp-1", "roles": ["GP"], "fund_ids": [], "org_id": "{ORG_ID}"}}',
        }
        response = await client.get(
            f"/api/v1/funds/{FUND_A}/investor/report-packs",
            headers=header,
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_advisor_authorized_fund_succeeds(self, client: AsyncClient):
        """ADVISOR with fund A in dev header can access fund A investor portal."""
        header = {
            "X-DEV-ACTOR": f'{{"actor_id": "adv-1", "roles": ["ADVISOR"], "fund_ids": ["{FUND_A}"], "org_id": "{ORG_ID}"}}',
        }
        response = await client.get(
            f"/api/v1/funds/{FUND_A}/investor/report-packs",
            headers=header,
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_multiple_fund_ids_investor(self, client: AsyncClient):
        """INVESTOR with multiple fund_ids can access both."""
        header = {
            "X-DEV-ACTOR": f'{{"actor_id": "inv-2", "roles": ["INVESTOR"], "fund_ids": ["{FUND_A}", "{FUND_B}"], "org_id": "{ORG_ID}"}}',
        }
        resp_a = await client.get(
            f"/api/v1/funds/{FUND_A}/investor/report-packs",
            headers=header,
        )
        resp_b = await client.get(
            f"/api/v1/funds/{FUND_B}/investor/report-packs",
            headers=header,
        )
        assert resp_a.status_code == 200
        assert resp_b.status_code == 200


# --- Unit tests for _resolve_fund_ids ---


class TestResolveFundIds:
    """Tests for the DB-backed fund membership resolution.

    These tests mock at the module level within _resolve_fund_ids to avoid
    needing a live database connection.
    """

    @pytest.mark.asyncio
    async def test_resolve_returns_empty_when_no_memberships(self, monkeypatch):
        """Returns empty list when no fund_memberships rows exist."""
        from unittest.mock import AsyncMock, MagicMock, patch

        fund_ids_result: list[uuid.UUID] = []

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = fund_ids_result

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session)

        with patch("app.core.db.engine.async_session_factory", mock_factory):
            from app.core.security.clerk_auth import _resolve_fund_ids
            result = await _resolve_fund_ids("user-1", uuid.UUID(ORG_ID))

        assert result == []

    @pytest.mark.asyncio
    async def test_resolve_returns_fund_ids_from_db(self, monkeypatch):
        """Returns fund_ids from DB when memberships exist."""
        from unittest.mock import AsyncMock, MagicMock, patch

        fund_a = uuid.UUID(FUND_A)
        fund_b = uuid.UUID(FUND_B)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [fund_a, fund_b]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session)

        with patch("app.core.db.engine.async_session_factory", mock_factory):
            from app.core.security.clerk_auth import _resolve_fund_ids
            result = await _resolve_fund_ids("user-1", uuid.UUID(ORG_ID))

        assert set(result) == {fund_a, fund_b}


# --- Role-matrix tests ---


class TestRoleMatrixFundAccess:
    """Prove admin and super-admin bypass is explicit, not inferred from empty memberships."""

    def test_admin_bypass_is_role_based_not_empty_list(self):
        """Admin access is from role check, not from empty fund_ids meaning 'all'."""
        actor_admin = Actor(
            actor_id="admin",
            name="Admin",
            email="admin@test.com",
            roles=[Role.ADMIN],
            fund_ids=[],
        )
        actor_investor = Actor(
            actor_id="investor",
            name="Investor",
            email="inv@test.com",
            roles=[Role.INVESTOR],
            fund_ids=[],
        )
        random_fund = uuid.uuid4()

        # Admin with empty fund_ids: access (role bypass)
        assert actor_admin.can_access_fund(random_fund)
        # Investor with empty fund_ids: denied (no bypass)
        assert not actor_investor.can_access_fund(random_fund)

    def test_super_admin_bypass_is_role_based(self):
        """Super-admin bypass is explicit role check."""
        actor = Actor(
            actor_id="sa",
            name="SA",
            email="sa@test.com",
            roles=[Role.SUPER_ADMIN],
            fund_ids=[],
        )
        assert actor.can_access_fund(uuid.uuid4())

    def test_all_non_admin_roles_require_membership(self):
        """Every non-admin role requires explicit fund_ids membership."""
        non_admin_roles = [
            Role.INVESTMENT_TEAM, Role.GP, Role.DIRECTOR,
            Role.COMPLIANCE, Role.AUDITOR, Role.INVESTOR, Role.ADVISOR,
        ]
        fund = uuid.uuid4()
        for role in non_admin_roles:
            actor = Actor(
                actor_id=f"user-{role}",
                name=str(role),
                email=f"{role}@test.com",
                roles=[role],
                fund_ids=[],
            )
            assert not actor.can_access_fund(fund), f"{role} with empty fund_ids should be denied"

    def test_non_admin_with_specific_fund_granted(self):
        """Non-admin roles with explicit fund_id get access to that fund only."""
        fund = uuid.uuid4()
        other_fund = uuid.uuid4()
        non_admin_roles = [
            Role.INVESTMENT_TEAM, Role.GP, Role.DIRECTOR,
            Role.COMPLIANCE, Role.AUDITOR, Role.INVESTOR, Role.ADVISOR,
        ]
        for role in non_admin_roles:
            actor = Actor(
                actor_id=f"user-{role}",
                name=str(role),
                email=f"{role}@test.com",
                roles=[role],
                fund_ids=[fund],
            )
            assert actor.can_access_fund(fund), f"{role} should access assigned fund"
            assert not actor.can_access_fund(other_fund), f"{role} should NOT access unassigned fund"
