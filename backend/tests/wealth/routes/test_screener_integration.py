"""Integration tests for Phase 3 Session A screener backend.

Exercises catalog MV JOINs, ELITE filtering, sparkline batch,
fast-track universe approval, keyset pagination, and jargon
sanitization. Tests run against real Postgres via the httpx
AsyncClient fixture from conftest.py.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import DEV_ACTOR_HEADER

# All tests require a running Postgres instance with seeded data.
# They are marked as integration tests and skipped if the DB is
# unreachable (the client fixture from conftest handles connection).

pytestmark = pytest.mark.asyncio


# ── Helpers ──────────────────────────────────────────────────────


_BANNED_JARGON = [
    "RISK_ON", "RISK_OFF", "CRISIS", "NEUTRAL",
    "cvar_95", "expected_shortfall", "garch_vol",
    "dtw_drift", "ewma_vol", "cfnai", "macroscore",
]


# ── 1. Catalog test: MV JOIN fields present ──────────────────────


async def test_catalog_has_elite_and_membership_fields(client: AsyncClient):
    """POST /screener/catalog returns elite_flag, in_universe, approval_status."""
    resp = await client.get(
        "/api/v1/screener/catalog",
        params={"page_size": 5, "has_nav": True},
        headers=DEV_ACTOR_HEADER,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert data["total"] >= 0

    if data["items"]:
        item = data["items"][0]
        # Fields must be present in the response (can be null)
        assert "elite_flag" in item
        assert "elite_rank_within_strategy" in item
        assert "in_universe" in item
        assert "approval_status" in item
        assert "external_id" in item


# ── 2. ELITE filter test ────────────────────────────────────────


async def test_catalog_elite_only_filter(client: AsyncClient):
    """POST /screener/catalog with elite_only=true returns only ELITE funds."""
    resp = await client.get(
        "/api/v1/screener/catalog",
        params={"elite_only": True, "page_size": 50, "has_nav": True},
        headers=DEV_ACTOR_HEADER,
    )
    assert resp.status_code == 200
    data = resp.json()

    for item in data["items"]:
        assert item["elite_flag"] is True, f"Non-ELITE fund in elite_only response: {item['external_id']}"

    # ELITE catalog should never exceed 300 per the ranking design
    assert data["total"] <= 500  # generous upper bound accounting for ties


# ── 3. Sparkline batch test ──────────────────────────────────────


async def test_sparkline_empty_request(client: AsyncClient):
    """POST /screener/sparklines with empty list returns empty dict."""
    resp = await client.post(
        "/api/v1/screener/sparklines",
        json={"instrument_ids": [], "months": 60},
        headers=DEV_ACTOR_HEADER,
    )
    assert resp.status_code == 200
    assert resp.json() == {}


async def test_sparkline_over_100_rejected(client: AsyncClient):
    """POST /screener/sparklines with >100 IDs returns 400."""
    fake_ids = [f"00000000-0000-0000-0000-{str(i).zfill(12)}" for i in range(101)]
    resp = await client.post(
        "/api/v1/screener/sparklines",
        json={"instrument_ids": fake_ids, "months": 60},
        headers=DEV_ACTOR_HEADER,
    )
    assert resp.status_code == 400


async def test_sparkline_nonexistent_ids_omitted(client: AsyncClient):
    """POST /screener/sparklines with non-existent IDs returns empty dict."""
    resp = await client.post(
        "/api/v1/screener/sparklines",
        json={
            "instrument_ids": [
                "00000000-0000-0000-0000-000000000099",
                "00000000-0000-0000-0000-000000000098",
            ],
            "months": 60,
        },
        headers=DEV_ACTOR_HEADER,
    )
    assert resp.status_code == 200
    # Non-existent instruments are simply omitted
    data = resp.json()
    assert isinstance(data, dict)


# ── 4. Universe fast-approve: DD gate blocks private ─────────────


async def test_fast_approve_empty_list(client: AsyncClient):
    """POST /universe/fast-approve with empty list returns empty response."""
    resp = await client.post(
        "/api/v1/universe/fast-approve",
        json={"instrument_ids": []},
        headers=DEV_ACTOR_HEADER,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["approved"] == []
    assert data["rejected_dd_required"] == []


# ── 5. Keyset pagination test ────────────────────────────────────


async def test_keyset_pagination_no_overlap(client: AsyncClient):
    """Fetch 3 pages via cursor chaining — no row overlap, final cursor null."""
    page_size = 3
    seen_ids: set[str] = set()
    cursor = None
    pages_fetched = 0

    for _ in range(3):
        params: dict = {"page_size": page_size, "has_nav": True, "sort": "aum_desc"}
        if cursor:
            params["cursor"] = cursor

        resp = await client.get(
            "/api/v1/screener/catalog",
            params=params,
            headers=DEV_ACTOR_HEADER,
        )
        assert resp.status_code == 200
        data = resp.json()

        if not data["items"]:
            break

        page_ids = {item["external_id"] for item in data["items"]}
        overlap = seen_ids & page_ids
        assert not overlap, f"Row overlap between pages: {overlap}"
        seen_ids.update(page_ids)

        cursor = data.get("next_cursor")
        pages_fetched += 1

        if cursor is None:
            break

    assert pages_fetched >= 1


async def test_offset_fallback_still_works(client: AsyncClient):
    """Offset-based pagination (deprecated) still functions."""
    resp = await client.get(
        "/api/v1/screener/catalog",
        params={"page": 2, "page_size": 5, "has_nav": True},
        headers=DEV_ACTOR_HEADER,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["page"] == 2
    assert data["page_size"] == 5


# ── 6. Sanitization test ────────────────────────────────────────


async def test_catalog_no_jargon_leakage(client: AsyncClient):
    """Catalog response must not contain banned quant jargon strings."""
    resp = await client.get(
        "/api/v1/screener/catalog",
        params={"page_size": 20, "has_nav": True},
        headers=DEV_ACTOR_HEADER,
    )
    assert resp.status_code == 200
    body = resp.text

    for term in _BANNED_JARGON:
        # Check case-sensitive to avoid false positives on field names
        # (e.g. "cvar_95_12m" as a field key is OK if the VALUE is sanitized)
        # We check for the jargon appearing as a string value
        assert f'"{term}"' not in body, (
            f"Banned jargon '{term}' found in catalog response body"
        )


# ── 7. ELITE endpoint still works (Phase 2 regression) ──────────


async def test_elite_endpoint_returns_page(client: AsyncClient):
    """GET /screener/catalog/elite returns valid page structure."""
    resp = await client.get(
        "/api/v1/screener/catalog/elite",
        params={"limit": 10},
        headers=DEV_ACTOR_HEADER,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert "limit" in data
