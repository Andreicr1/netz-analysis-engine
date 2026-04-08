"""Discovery Analysis — returns-risk endpoint tests (Phase 5 Task 5.1).

Skipped at the module level because the required fixtures
(``async_client``, ``dev_headers``, ``sample_fund_id``,
``sample_private_fund_id``) and seeded prod data are not yet wired into
the backend test harness. The bodies are preserved so Phase 5 follow-up
work (test harness bootstrap) can enable them without rewriting.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(
    reason="requires seeded prod data + dev_headers/sample_fund_id fixtures",
)


@pytest.mark.asyncio
async def test_returns_risk_default_3y(
    async_client,  # noqa: ANN001
    dev_headers,  # noqa: ANN001
    sample_fund_id,  # noqa: ANN001
) -> None:
    resp = await async_client.get(
        f"/api/wealth/discovery/funds/{sample_fund_id}/analysis/returns-risk",
        headers=dev_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["window"] == "3y"
    assert "nav_series" in body
    assert "monthly_returns" in body
    assert "rolling_metrics" in body
    assert "return_distribution" in body
    assert "risk_metrics" in body


@pytest.mark.asyncio
async def test_returns_risk_custom_window(
    async_client,  # noqa: ANN001
    dev_headers,  # noqa: ANN001
    sample_fund_id,  # noqa: ANN001
) -> None:
    resp = await async_client.get(
        f"/api/wealth/discovery/funds/{sample_fund_id}/analysis/returns-risk?window=5y",
        headers=dev_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["window"] == "5y"


@pytest.mark.asyncio
async def test_private_fund_returns_empty(
    async_client,  # noqa: ANN001
    dev_headers,  # noqa: ANN001
    sample_private_fund_id,  # noqa: ANN001
) -> None:
    resp = await async_client.get(
        f"/api/wealth/discovery/funds/{sample_private_fund_id}/analysis/returns-risk",
        headers=dev_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["disclosure"]["has_nav"] is False
    assert body["nav_series"] == []
