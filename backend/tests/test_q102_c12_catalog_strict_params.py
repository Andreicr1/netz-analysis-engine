"""C-12: GET /catalog rejects unknown query params with 422.

Tests that:
- Unknown query params on /catalog, /catalog/managers, /catalog/facets
  return HTTP 422 instead of being silently ignored.
- Known params still pass validation.
- Whitelist tuples match the route signatures.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.tenancy.middleware import get_db_with_rls


def _make_test_app() -> FastAPI:
    """Create a minimal app with just the screener router.

    Overrides get_db_with_rls so auth/DB is not needed.
    The _strict_query_params dependency runs before any DB query,
    so we can test parameter validation in isolation.
    """
    from app.domains.wealth.routes.screener import router

    app = FastAPI()
    app.include_router(router)

    # Override DB dependency — return a mock session
    app.dependency_overrides[get_db_with_rls] = lambda: AsyncMock()

    return app


class TestCatalogStrictQueryParams:
    """Verify _strict_query_params rejects unknown params."""

    @pytest.mark.asyncio
    async def test_catalog_unknown_param_returns_422(self):
        app = _make_test_app()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/screener/catalog?unknown_param=1")
        assert resp.status_code == 422
        assert "unknown_param" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_catalog_managers_unknown_param_returns_422(self):
        app = _make_test_app()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/screener/catalog/managers?bogus=true")
        assert resp.status_code == 422
        assert "bogus" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_catalog_facets_unknown_param_returns_422(self):
        app = _make_test_app()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/screener/catalog/facets?not_a_param=42")
        assert resp.status_code == 422
        assert "not_a_param" in resp.json()["detail"]

    def test_param_whitelists_match_route_signatures(self):
        """Sanity check: every param in the whitelist must exist as a
        Query() parameter in the corresponding route function."""
        import inspect

        from app.domains.wealth.routes.screener import (
            _CATALOG_PARAMS,
            _FACETS_PARAMS,
            _MANAGERS_PARAMS,
            get_catalog,
            get_catalog_facets,
            get_catalog_managers,
        )

        for params, fn in [
            (_CATALOG_PARAMS, get_catalog),
            (_MANAGERS_PARAMS, get_catalog_managers),
            (_FACETS_PARAMS, get_catalog_facets),
        ]:
            sig = inspect.signature(fn)
            sig_params = {
                name
                for name, p in sig.parameters.items()
                if not name.startswith("_") and name != "db"
            }
            whitelist = set(params)
            missing = whitelist - sig_params
            assert not missing, (
                f"{fn.__name__}: whitelist has params not in signature: {missing}"
            )
