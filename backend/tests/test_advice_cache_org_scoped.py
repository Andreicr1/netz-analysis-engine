"""Tests for advice cache org-scoped key — PR-Q143 (C-12 cross-tenant defense).

Validates that:
1. _hash_advice_input includes organization_id in the hash.
2. Redis key prefix includes org_id for human-readable inspection.
3. Same portfolio + different org yields different cache key (isolation).
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domains.wealth.routes.model_portfolios import (
    _get_cached_advice,
    _hash_advice_input,
    _set_cached_advice,
)

# ---------------------------------------------------------------------------
# 1. Hash includes organization_id
# ---------------------------------------------------------------------------


class TestHashIncludesOrganizationId:
    def test_same_portfolio_different_org_yields_different_hash(self):
        """Same portfolio_id + updated_at but different org_id -> different cache key."""
        h1 = _hash_advice_input("org-aaa", "port-123", "2026-01-01T00:00:00")
        h2 = _hash_advice_input("org-bbb", "port-123", "2026-01-01T00:00:00")
        assert h1 != h2

    def test_same_org_same_inputs_same_hash(self):
        """Identical inputs should produce identical hash (deterministic)."""
        h1 = _hash_advice_input("org-aaa", "port-123", "2026-01-01T00:00:00")
        h2 = _hash_advice_input("org-aaa", "port-123", "2026-01-01T00:00:00")
        assert h1 == h2

    def test_hash_length(self):
        h = _hash_advice_input("org-x", "port-y", "ts")
        assert len(h) == 24

    def test_hash_matches_expected_payload(self):
        """Hash is SHA-256 of 'org|portfolio|updated_at|date'."""
        org = "org-unit-test"
        pid = "port-42"
        ts = "2026-04-29T12:00:00"
        today = date.today().isoformat()
        payload = f"{org}|{pid}|{ts}|{today}"
        expected = hashlib.sha256(payload.encode()).hexdigest()[:24]
        assert _hash_advice_input(org, pid, ts) == expected


# ---------------------------------------------------------------------------
# 2. Redis key prefix includes org_id
# ---------------------------------------------------------------------------


class TestRedisKeyPrefixIncludesOrgId:
    @pytest.mark.asyncio
    async def test_get_uses_org_scoped_key(self):
        """_get_cached_advice reads from 'advice:cache:{org_id}:{cache_key}'."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps({"a": 1}).encode())
        mock_redis.aclose = AsyncMock()

        with patch(
            "app.core.jobs.tracker.get_redis_pool",
            return_value=MagicMock(),
        ), patch(
            "redis.asyncio.Redis",
            return_value=mock_redis,
        ):
            result = await _get_cached_advice("org-abc", "hashval123")

        mock_redis.get.assert_awaited_once_with("advice:cache:org-abc:hashval123")
        assert result == {"a": 1}

    @pytest.mark.asyncio
    async def test_set_uses_org_scoped_key(self):
        """_set_cached_advice writes to 'advice:cache:{org_id}:{cache_key}'."""
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()
        mock_redis.aclose = AsyncMock()

        with patch(
            "app.core.jobs.tracker.get_redis_pool",
            return_value=MagicMock(),
        ), patch(
            "redis.asyncio.Redis",
            return_value=mock_redis,
        ):
            await _set_cached_advice("org-xyz", "hashval456", {"b": 2}, ttl=120)

        mock_redis.set.assert_awaited_once()
        call_args = mock_redis.set.call_args
        assert call_args[0][0] == "advice:cache:org-xyz:hashval456"
        assert call_args[1]["ex"] == 120


# ---------------------------------------------------------------------------
# 3. Cache isolated across orgs
# ---------------------------------------------------------------------------


class TestCacheIsolatedAcrossOrgs:
    @pytest.mark.asyncio
    async def test_cache_miss_for_different_org(self):
        """Write advice for org A, read with org B context -> cache miss."""
        store: dict[str, bytes] = {}

        async def mock_get(key: str) -> bytes | None:
            return store.get(key)

        async def mock_set(key: str, value: str | bytes, *, ex: int = 0) -> None:
            store[key] = value if isinstance(value, bytes) else value.encode()

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=mock_get)
        mock_redis.set = AsyncMock(side_effect=mock_set)
        mock_redis.aclose = AsyncMock()

        with patch(
            "app.core.jobs.tracker.get_redis_pool",
            return_value=MagicMock(),
        ), patch(
            "redis.asyncio.Redis",
            return_value=mock_redis,
        ):
            # Same portfolio hash, but org A writes
            cache_key = "shared-hash-value"
            await _set_cached_advice("org-A", cache_key, {"advice": "for A"})

            # org A reads -> hit
            hit = await _get_cached_advice("org-A", cache_key)
            assert hit is not None
            assert hit["advice"] == "for A"

            # org B reads same cache_key -> miss (different prefix)
            miss = await _get_cached_advice("org-B", cache_key)
            assert miss is None
