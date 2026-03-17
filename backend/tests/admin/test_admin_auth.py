"""Tests for admin auth dependency."""

from __future__ import annotations

import uuid

import pytest

from app.core.security.clerk_auth import CLERK_TO_ROLE, Actor
from app.shared.enums import Role


class TestRequireSuperAdmin:
    """Test require_super_admin dependency logic."""

    def test_super_admin_role_exists(self):
        """SUPER_ADMIN should be a valid Role enum value."""
        assert Role.SUPER_ADMIN == "SUPER_ADMIN"

    def test_actor_with_super_admin(self):
        actor = Actor(
            actor_id="user_1",
            name="Admin",
            email="admin@netz.capital",
            roles=[Role.SUPER_ADMIN],
            organization_id=uuid.uuid4(),
        )
        assert Role.SUPER_ADMIN in actor.roles

    def test_actor_without_super_admin(self):
        actor = Actor(
            actor_id="user_2",
            name="Regular Admin",
            email="org_admin@acme.com",
            roles=[Role.ADMIN],
            organization_id=uuid.uuid4(),
        )
        assert Role.SUPER_ADMIN not in actor.roles

    def test_super_admin_has_role_check(self):
        """SUPER_ADMIN should be recognized by has_role() as superuser."""
        actor = Actor(
            actor_id="user_1",
            name="Admin",
            email="admin@netz.capital",
            roles=[Role.SUPER_ADMIN],
        )
        # SUPER_ADMIN should pass has_role for any role
        assert actor.has_role(Role.INVESTMENT_TEAM)
        assert actor.has_role(Role.COMPLIANCE)
        assert actor.has_role(Role.GP)

    def test_org_admin_not_super_admin(self):
        """org:admin (ADMIN role) should NOT pass as SUPER_ADMIN."""
        actor = Actor(
            actor_id="user_2",
            name="Org Admin",
            email="admin@acme.com",
            roles=[Role.ADMIN],
        )
        assert Role.SUPER_ADMIN not in actor.roles

    def test_admin_has_role_escalation(self):
        """ADMIN role also passes has_role() for any role (design decision)."""
        actor = Actor(
            actor_id="user_3",
            name="Org Admin",
            email="admin@acme.com",
            roles=[Role.ADMIN],
        )
        assert actor.has_role(Role.INVESTMENT_TEAM)

    def test_regular_user_no_escalation(self):
        """INVESTOR role should NOT pass has_role for INVESTMENT_TEAM."""
        actor = Actor(
            actor_id="user_4",
            name="Investor",
            email="investor@acme.com",
            roles=[Role.INVESTOR],
        )
        assert not actor.has_role(Role.INVESTMENT_TEAM)

    def test_can_access_fund_super_admin(self):
        """SUPER_ADMIN bypasses fund_ids check."""
        actor = Actor(
            actor_id="user_1",
            name="Admin",
            email="admin@netz.capital",
            roles=[Role.SUPER_ADMIN],
            fund_ids=[],
        )
        assert actor.can_access_fund(uuid.uuid4())

    def test_investor_limited_fund_access(self):
        """INVESTOR can only access their assigned funds."""
        fund_id = uuid.uuid4()
        other_fund = uuid.uuid4()
        actor = Actor(
            actor_id="user_5",
            name="Investor",
            email="investor@acme.com",
            roles=[Role.INVESTOR],
            fund_ids=[fund_id],
        )
        assert actor.can_access_fund(fund_id)
        assert not actor.can_access_fund(other_fund)


class TestClerkRoleMapping:
    """Test Clerk role to internal Role mapping."""

    def test_super_admin_mapping(self):
        assert CLERK_TO_ROLE.get("org:super_admin") == Role.SUPER_ADMIN

    def test_admin_mapping(self):
        assert CLERK_TO_ROLE.get("org:admin") == Role.ADMIN

    def test_investment_team_mapping(self):
        assert CLERK_TO_ROLE.get("org:investment_team") == Role.INVESTMENT_TEAM

    def test_all_roles_mapped(self):
        """All Role enum values should have a Clerk mapping."""
        mapped_roles = set(CLERK_TO_ROLE.values())
        for role in Role:
            assert role in mapped_roles, f"Role {role} has no Clerk mapping"

    def test_unknown_role_returns_none(self):
        assert CLERK_TO_ROLE.get("org:unknown") is None
