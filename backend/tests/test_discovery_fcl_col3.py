"""Integration tests for Discovery FCL Col3 routes (fact sheet + DD).

Skipped by default — relies on seeded production data and fixture
plumbing (``async_client``, ``dev_headers``, ``sample_fund_id``)
that does not exist in the current test infra.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(
    reason="Requires seeded prod data + dev_headers/sample_fund_id fixtures",
)


@pytest.mark.asyncio
async def test_fact_sheet_returns_aggregated_payload(
    async_client, dev_headers, sample_fund_id,  # type: ignore[no-untyped-def]
) -> None:
    resp = await async_client.get(
        f"/api/v1/wealth/discovery/funds/{sample_fund_id}/fact-sheet",
        headers=dev_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "fund" in body
    assert "classes" in body


@pytest.mark.asyncio
async def test_dd_report_snapshot_returns_chapters(
    async_client, dev_headers, sample_fund_id,  # type: ignore[no-untyped-def]
) -> None:
    resp = await async_client.get(
        f"/api/v1/wealth/discovery/funds/{sample_fund_id}/dd-report/snapshot",
        headers=dev_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "chapters" in body
    assert isinstance(body["chapters"], list)


@pytest.mark.asyncio
async def test_fact_sheet_404_for_unknown_fund(
    async_client, dev_headers,  # type: ignore[no-untyped-def]
) -> None:
    resp = await async_client.get(
        "/api/v1/wealth/discovery/funds/NONEXISTENT/fact-sheet",
        headers=dev_headers,
    )
    assert resp.status_code == 404
