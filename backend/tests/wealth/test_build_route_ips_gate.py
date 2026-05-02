"""PR-BE-5 — route-level Strategic IPS approval gate for /portfolios/{id}/build."""

from __future__ import annotations

import asyncio
import json
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

ORG_A = uuid.UUID("00000000-0000-0000-0000-000000000001")
BOOTSTRAP_ORG = uuid.UUID("403d8392-0000-0000-0000-000000000000")


def _dev_header(
    *,
    org: uuid.UUID = ORG_A,
    roles: tuple[str, ...] = ("ADMIN", "INVESTMENT_TEAM"),
) -> dict[str, str]:
    return {
        "X-DEV-ACTOR": json.dumps(
            {
                "actor_id": "test-user",
                "roles": list(roles),
                "fund_ids": [],
                "org_id": str(org),
            },
        ),
    }


class _ScalarResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _FakeBuildGateSession:
    def __init__(
        self,
        *,
        portfolio_id: uuid.UUID,
        org_id: uuid.UUID,
        portfolio_profile: str,
        approved_profiles: set[str],
    ) -> None:
        self.portfolio_id = portfolio_id
        self.org_id = org_id
        self.portfolio = SimpleNamespace(
            id=portfolio_id,
            organization_id=org_id,
            profile=portfolio_profile,
        )
        self.approved_profiles = approved_profiles
        self.approval_profiles_checked: list[str] = []
        self.added: list[Any] = []
        self.execute = AsyncMock(side_effect=self._execute)
        self.flush = AsyncMock()
        self.commit = AsyncMock()
        self.add = MagicMock(side_effect=self.added.append)

    async def __aenter__(self) -> "_FakeBuildGateSession":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        return None

    async def _execute(self, stmt: Any, _params: dict[str, Any] | None = None) -> _ScalarResult:
        sql = str(getattr(stmt, "text", stmt))
        if "SET LOCAL app.current_organization_id" in sql:
            return _ScalarResult(None)
        if "FROM model_portfolios" in sql:
            return _ScalarResult(self.portfolio)
        if "FROM allocation_approvals" in sql:
            params = stmt.compile().params
            profile = next(
                value for key, value in params.items() if key.startswith("profile")
            )
            self.approval_profiles_checked.append(profile)
            approval_id = uuid.uuid4() if profile in self.approved_profiles else None
            return _ScalarResult(approval_id)
        raise AssertionError(f"unexpected SQL in fake build gate session: {sql}")


@pytest.fixture
def reset_idempotency_storage():
    from app.core.runtime import gates
    from app.core.runtime.idempotency import InMemoryIdempotencyStorage

    storage = gates.get_idempotency_storage()
    mem = InMemoryIdempotencyStorage()
    saved = (
        storage.get_result,
        storage.set_result,
        storage.try_acquire,
        storage.release,
    )
    storage.get_result = mem.get_result  # type: ignore[method-assign]
    storage.set_result = mem.set_result  # type: ignore[method-assign]
    storage.try_acquire = mem.try_acquire  # type: ignore[method-assign]
    storage.release = mem.release  # type: ignore[method-assign]
    try:
        yield mem
    finally:
        (
            storage.get_result,
            storage.set_result,
            storage.try_acquire,
            storage.release,
        ) = saved  # type: ignore[method-assign]


def _patch_build_gate_session(
    monkeypatch: pytest.MonkeyPatch,
    session: _FakeBuildGateSession,
) -> None:
    from app.domains.wealth.routes.portfolios import builder as builder_mod

    monkeypatch.setattr(builder_mod, "async_session_factory", lambda: session)


async def test_build_with_approved_ips_returns_202_and_invokes_worker(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    reset_idempotency_storage,
) -> None:
    from app.domains.wealth.routes.portfolios import builder as builder_mod

    portfolio_id = uuid.uuid4()
    session = _FakeBuildGateSession(
        portfolio_id=portfolio_id,
        org_id=ORG_A,
        portfolio_profile="moderate",
        approved_profiles={"moderate"},
    )
    _patch_build_gate_session(monkeypatch, session)
    worker = AsyncMock()
    monkeypatch.setattr(builder_mod, "_build_portfolio_worker", worker)
    monkeypatch.setattr(builder_mod, "register_job_owner", AsyncMock())

    resp = await client.post(
        f"/api/v1/portfolios/{portfolio_id}/build",
        headers=_dev_header(),
    )

    assert resp.status_code == 202
    body = resp.json()
    assert uuid.UUID(body["job_id"])
    assert body["stream_url"] == f"/api/v1/jobs/{body['job_id']}/stream"
    assert body["status"] == "accepted"
    assert session.approval_profiles_checked == ["moderate"]
    worker.assert_called_once()
    await asyncio.sleep(0)


async def test_build_without_approved_ips_returns_409_audits_and_skips_worker(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    reset_idempotency_storage,
) -> None:
    from app.domains.wealth.routes.portfolios import builder as builder_mod

    portfolio_id = uuid.uuid4()
    session = _FakeBuildGateSession(
        portfolio_id=portfolio_id,
        org_id=ORG_A,
        portfolio_profile="moderate",
        approved_profiles=set(),
    )
    _patch_build_gate_session(monkeypatch, session)
    worker = AsyncMock()
    register_job_owner = AsyncMock()
    monkeypatch.setattr(builder_mod, "_build_portfolio_worker", worker)
    monkeypatch.setattr(builder_mod, "register_job_owner", register_job_owner)

    headers = {**_dev_header(), "Idempotency-Key": "blocked-retry"}
    r1 = await client.post(f"/api/v1/portfolios/{portfolio_id}/build", headers=headers)
    r2 = await client.post(f"/api/v1/portfolios/{portfolio_id}/build", headers=headers)

    assert r1.status_code == 409
    assert r2.status_code == 409
    expected_detail = {
        "error": "ips_not_approved",
        "message": (
            "No approved Strategic IPS exists for profile 'moderate'. "
            "Approve a proposal in the Strategic stage before constructing "
            "this portfolio."
        ),
        "remediation_path": "/api/v1/allocation/moderate/approve-proposal",
    }
    assert r1.json()["detail"] == expected_detail
    assert r2.json()["detail"] == expected_detail
    assert len(session.added) == 2
    assert session.added[0].action == "portfolio_build_ips_gate_blocked"
    assert session.added[0].after_state["error"] == "ips_not_approved"
    assert session.commit.await_count == 2
    register_job_owner.assert_not_called()
    worker.assert_not_called()


async def test_bootstrap_self_approval_policy_does_not_bypass_ips_gate(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    reset_idempotency_storage,
) -> None:
    from app.domains.wealth.routes.portfolios import builder as builder_mod

    portfolio_id = uuid.uuid4()
    session = _FakeBuildGateSession(
        portfolio_id=portfolio_id,
        org_id=BOOTSTRAP_ORG,
        portfolio_profile="conservative",
        approved_profiles=set(),
    )
    _patch_build_gate_session(monkeypatch, session)
    worker = AsyncMock()
    monkeypatch.setattr(builder_mod, "_build_portfolio_worker", worker)
    monkeypatch.setattr(builder_mod, "register_job_owner", AsyncMock())

    resp = await client.post(
        f"/api/v1/portfolios/{portfolio_id}/build",
        headers=_dev_header(org=BOOTSTRAP_ORG),
    )

    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "ips_not_approved"
    assert session.approval_profiles_checked == ["conservative"]
    worker.assert_not_called()


async def test_aggressive_portfolio_profile_alias_checks_growth_ips_approval(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    reset_idempotency_storage,
) -> None:
    from app.domains.wealth.routes.portfolios import builder as builder_mod

    portfolio_id = uuid.uuid4()
    session = _FakeBuildGateSession(
        portfolio_id=portfolio_id,
        org_id=ORG_A,
        portfolio_profile="aggressive",
        approved_profiles={"growth"},
    )
    _patch_build_gate_session(monkeypatch, session)
    worker = AsyncMock()
    monkeypatch.setattr(builder_mod, "_build_portfolio_worker", worker)
    monkeypatch.setattr(builder_mod, "register_job_owner", AsyncMock())

    resp = await client.post(
        f"/api/v1/portfolios/{portfolio_id}/build",
        headers=_dev_header(),
    )

    assert resp.status_code == 202
    assert session.approval_profiles_checked == ["growth"]
    worker.assert_called_once()
