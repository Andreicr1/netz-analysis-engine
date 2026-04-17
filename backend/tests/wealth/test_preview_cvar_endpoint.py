"""PR-A13.1 — POST /preview-cvar endpoint tests.

Unit coverage:
- Request validation bounds
- Cache key determinism / quantization
- Operator signal derivation from cascade telemetry shape
- Endpoint happy path with ``_run_construction_async`` monkeypatched
- Upstream data missing → 422
- Non-UUID portfolio id → 400
- Invalid body (out-of-range cvar_limit) → 400

Integration with the real optimizer cascade is exercised by the live-DB
smoke recorded in the PR body (see Section F.10 of the spec).
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.domains.wealth.routes.portfolios.builder import (
    _operator_signal_from_cascade,
    _preview_cache_key,
)
from app.domains.wealth.schemas.preview import (
    AchievableReturnBandDTO,
    OperatorSignalDTO,
    PreviewCvarRequest,
    PreviewCvarResponse,
)

# Only async tests get the asyncio marker; apply per-test where needed.

ORG_A = "00000000-0000-0000-0000-000000000001"
ORG_B = "00000000-0000-0000-0000-000000000002"


def _dev_header(
    *, org: str = ORG_A, roles: tuple[str, ...] = ("ADMIN", "INVESTMENT_TEAM"),
) -> dict[str, str]:
    return {
        "X-DEV-ACTOR": json.dumps({
            "actor_id": f"test-{org[-1]}",
            "roles": list(roles),
            "fund_ids": [],
            "org_id": org,
        }),
    }


# ── Request schema ────────────────────────────────────────────────────


def test_request_accepts_valid_cvar_limit() -> None:
    req = PreviewCvarRequest(cvar_limit=0.025)
    assert req.cvar_limit == 0.025
    assert req.mandate is None


def test_request_rejects_cvar_below_floor() -> None:
    with pytest.raises(ValidationError):
        PreviewCvarRequest(cvar_limit=0.0001)


def test_request_rejects_cvar_above_ceiling() -> None:
    with pytest.raises(ValidationError):
        PreviewCvarRequest(cvar_limit=0.25)


def test_request_rejects_unknown_mandate() -> None:
    with pytest.raises(ValidationError):
        PreviewCvarRequest(cvar_limit=0.05, mandate="custom")  # type: ignore[arg-type]


def test_request_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        PreviewCvarRequest.model_validate({"cvar_limit": 0.05, "unknown": 1})


# ── Cache key ─────────────────────────────────────────────────────────


def test_cache_key_deterministic() -> None:
    a = _preview_cache_key(ORG_A, "pid", 0.025)
    b = _preview_cache_key(ORG_A, "pid", 0.025)
    assert a == b
    assert a.startswith("preview_cvar:v1:")


def test_cache_key_quantizes_to_4_decimals() -> None:
    # 0.02504 rounds to 0.0250 (matches slider step + column precision).
    assert _preview_cache_key(ORG_A, "p", 0.02504) == _preview_cache_key(ORG_A, "p", 0.0250)


def test_cache_key_differs_on_cvar() -> None:
    assert _preview_cache_key(ORG_A, "p", 0.025) != _preview_cache_key(ORG_A, "p", 0.030)


def test_cache_key_differs_on_org() -> None:
    assert _preview_cache_key(ORG_A, "p", 0.025) != _preview_cache_key(ORG_B, "p", 0.025)


def test_cache_key_differs_on_portfolio() -> None:
    assert _preview_cache_key(ORG_A, "p1", 0.025) != _preview_cache_key(ORG_A, "p2", 0.025)


# ── Operator signal ────────────────────────────────────────────────────


def test_operator_signal_phase1_is_feasible() -> None:
    cascade = {"winning_phase": "phase_1_ru_max_return", "phase_attempts": []}
    assert _operator_signal_from_cascade(cascade, None, 0.025)["kind"] == "feasible"


def test_operator_signal_phase3_within_limit_is_feasible() -> None:
    cascade = {
        "winning_phase": "phase_3_min_cvar",
        "phase_attempts": [{
            "phase": "phase_3_min_cvar",
            "cvar_within_limit": True,
        }],
    }
    assert _operator_signal_from_cascade(cascade, None, 0.025)["kind"] == "feasible"


def test_operator_signal_phase3_above_limit_flags_floor() -> None:
    cascade = {
        "winning_phase": "phase_3_min_cvar",
        "phase_attempts": [{
            "phase": "phase_3_min_cvar",
            "cvar_within_limit": False,
        }],
    }
    sig = _operator_signal_from_cascade(cascade, None, 0.002)
    assert sig["kind"] == "cvar_limit_below_universe_floor"
    assert sig["message_key"] == "cvar_limit_below_universe_floor"


def test_operator_signal_upstream_heuristic() -> None:
    cascade = {"winning_phase": "upstream_heuristic", "phase_attempts": []}
    sig = _operator_signal_from_cascade(cascade, None, 0.025)
    assert sig["kind"] == "upstream_data_missing"


def test_operator_signal_upstream_reason_from_fallback() -> None:
    sig = _operator_signal_from_cascade(None, "dedup_collapsed_too_far", 0.025)
    assert sig["kind"] == "upstream_data_missing"
    assert sig["message_key"] == "dedup_collapsed_too_far"


# ── Endpoint — error paths ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_preview_rejects_non_uuid(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/portfolios/not-a-uuid/preview-cvar",
        headers=_dev_header(),
        json={"cvar_limit": 0.025},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_preview_rejects_out_of_range_cvar(client: AsyncClient) -> None:
    portfolio_id = str(uuid.uuid4())
    resp = await client.post(
        f"/api/v1/portfolios/{portfolio_id}/preview-cvar",
        headers=_dev_header(),
        json={"cvar_limit": 0.5},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_preview_requires_ic_role(client: AsyncClient) -> None:
    portfolio_id = str(uuid.uuid4())
    resp = await client.post(
        f"/api/v1/portfolios/{portfolio_id}/preview-cvar",
        headers=_dev_header(roles=("INVESTOR",)),
        json={"cvar_limit": 0.025},
    )
    assert resp.status_code == 403


# ── Endpoint — happy path (mocked compute) ────────────────────────────


@pytest.fixture
def patch_preview_compute_happy():
    """Bypass portfolio lookup + _run_construction_async with a stub band."""
    mock_portfolio = type("P", (), {"id": uuid.uuid4(), "profile": "moderate"})()

    async def _fake_execute_scalar(*_a: Any, **_kw: Any) -> Any:
        class _Res:
            def scalar_one_or_none(self) -> Any:
                return mock_portfolio
        return _Res()

    band = {
        "lower": 0.12,
        "upper": 0.18,
        "lower_at_cvar": 0.012,
        "upper_at_cvar": 0.049,
    }
    compute_result = {
        "achievable_return_band": band,
        "min_achievable_cvar": 0.012,
        "operator_signal": {
            "kind": "feasible",
            "binding": None,
            "message_key": "feasible",
        },
    }

    # Patch session factory helpers and _compute_preview to avoid DB.
    ctx = patch(
        "app.domains.wealth.routes.portfolios.builder._compute_preview",
        new=AsyncMock(return_value=compute_result),
    )
    ctx2 = patch(
        "app.domains.wealth.routes.portfolios.builder.async_session_factory",
    )
    ctx3 = patch(
        "app.domains.wealth.routes.portfolios.builder._set_rls_org",
        new=AsyncMock(return_value=None),
    )
    with ctx, ctx2 as session_factory, ctx3:
        class _FakeSession:
            async def __aenter__(self) -> "_FakeSession":
                return self

            async def __aexit__(self, *a: Any) -> None:
                return None

            async def execute(self, *_a: Any, **_kw: Any) -> Any:
                return await _fake_execute_scalar()

        session_factory.return_value = _FakeSession()
        yield


@pytest.mark.asyncio
async def test_preview_happy_path_returns_dto(
    client: AsyncClient,
    patch_preview_compute_happy,
) -> None:
    portfolio_id = str(uuid.uuid4())
    resp = await client.post(
        f"/api/v1/portfolios/{portfolio_id}/preview-cvar",
        headers=_dev_header(),
        json={"cvar_limit": 0.025},
    )
    assert resp.status_code == 200
    body = resp.json()
    PreviewCvarResponse.model_validate(body)  # shape check
    assert body["operator_signal"]["kind"] == "feasible"
    assert body["achievable_return_band"]["lower"] == 0.12
    assert body["achievable_return_band"]["upper"] == 0.18
    assert body["cached"] is False
    assert body["wall_ms"] >= 0


@pytest.mark.asyncio
async def test_preview_upstream_failure_returns_422(
    client: AsyncClient,
) -> None:
    from app.domains.wealth.routes.portfolios import builder as builder_mod

    mock_portfolio = type("P", (), {"id": uuid.uuid4(), "profile": "moderate"})()

    async def _fake_execute(*_a: Any, **_kw: Any) -> Any:
        class _Res:
            def scalar_one_or_none(self) -> Any:
                return mock_portfolio
        return _Res()

    class _FakeSession:
        async def __aenter__(self) -> "_FakeSession":
            return self
        async def __aexit__(self, *a: Any) -> None:
            return None
        async def execute(self, *_a: Any, **_kw: Any) -> Any:
            return await _fake_execute()

    async def _raise(*_a: Any, **_kw: Any) -> Any:
        raise builder_mod._PreviewUpstreamError("dedup_collapsed_too_far")

    portfolio_id = str(uuid.uuid4())
    with (
        patch.object(builder_mod, "async_session_factory", return_value=_FakeSession()),
        patch.object(builder_mod, "_set_rls_org", new=AsyncMock(return_value=None)),
        patch.object(builder_mod, "_compute_preview", new=_raise),
    ):
        resp = await client.post(
            f"/api/v1/portfolios/{portfolio_id}/preview-cvar",
            headers=_dev_header(),
            json={"cvar_limit": 0.025},
        )
    assert resp.status_code == 422
    body = resp.json()
    assert body["detail"]["operator_signal"]["message_key"] == "dedup_collapsed_too_far"


# ── DTO round-trip ────────────────────────────────────────────────────


def test_response_dto_round_trip() -> None:
    resp = PreviewCvarResponse(
        achievable_return_band=AchievableReturnBandDTO(
            lower=0.1, upper=0.2, lower_at_cvar=0.01, upper_at_cvar=0.05,
        ),
        min_achievable_cvar=0.01,
        operator_signal=OperatorSignalDTO(
            kind="feasible", binding=None, message_key="feasible",
        ),
        cached=True,
        wall_ms=42,
    )
    data = resp.model_dump(mode="json")
    reparsed = PreviewCvarResponse.model_validate(data)
    assert reparsed == resp
