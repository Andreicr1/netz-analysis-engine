"""Integration tests for Discovery FCL manager/fund routes.

Skipped by default: the keyset/cache tests require seeded production
data plus ``dev_headers`` / ``sample_manager_id`` fixtures that do not
exist in the current test infrastructure. Keeping the file (rather
than deleting it) so the test contract lives next to the routes and
can be enabled once a seeded fixture DB lands.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(
    reason="Requires seeded prod data + dev_headers/sample_manager_id fixtures",
)


@pytest.mark.asyncio
async def test_managers_list_returns_200_with_rows(async_client, dev_headers) -> None:  # type: ignore[no-untyped-def]
    resp = await async_client.post(
        "/api/v1/wealth/discovery/managers",
        json={"filters": {}, "limit": 10},
        headers=dev_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "rows" in body
    assert isinstance(body["rows"], list)
    if body["rows"]:
        row = body["rows"][0]
        assert "manager_id" in row
        assert "fund_count" in row


@pytest.mark.asyncio
async def test_funds_by_manager_returns_ordered_by_aum(
    async_client, dev_headers, sample_manager_id,  # type: ignore[no-untyped-def]
) -> None:
    resp = await async_client.post(
        f"/api/v1/wealth/discovery/managers/{sample_manager_id}/funds",
        json={"limit": 20},
        headers=dev_headers,
    )
    assert resp.status_code == 200
    rows = resp.json()["rows"]
    aums = [r["aum_usd"] for r in rows if r["aum_usd"] is not None]
    assert aums == sorted(aums, reverse=True)


@pytest.mark.asyncio
async def test_managers_cache_hit_is_faster(async_client, dev_headers) -> None:  # type: ignore[no-untyped-def]
    import time

    payload = {"filters": {"strategies": ["Private Credit"]}, "limit": 10}
    t0 = time.perf_counter()
    await async_client.post(
        "/api/v1/wealth/discovery/managers", json=payload, headers=dev_headers,
    )
    cold = time.perf_counter() - t0
    t1 = time.perf_counter()
    await async_client.post(
        "/api/v1/wealth/discovery/managers", json=payload, headers=dev_headers,
    )
    warm = time.perf_counter() - t1
    assert warm < cold
