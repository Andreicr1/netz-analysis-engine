"""Integration test for the Discovery DD report SSE stream.

Skipped by default — requires seeded prod data + dev fixtures.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(
    reason="Requires seeded prod data + dev_headers/sample_fund_id fixtures",
)


@pytest.mark.asyncio
async def test_dd_stream_returns_event_stream_content_type(
    async_client, dev_headers, sample_fund_id,  # type: ignore[no-untyped-def]
) -> None:
    async with async_client.stream(
        "GET",
        f"/api/v1/wealth/discovery/funds/{sample_fund_id}/dd-report/stream",
        headers=dev_headers,
    ) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
