"""ISIN → Yahoo Finance ticker resolution via OpenFIGI batch API.

Fully standalone: zero imports from ``app.*``.
"""
from __future__ import annotations

from typing import Any

import httpx
import structlog

from data_providers.esma.models import IsinResolution
from data_providers.esma.shared import (
    OPENFIGI_BATCH_SIZE,
    check_openfigi_rate,
    resolve_isin_to_ticker_batch,
)

logger = structlog.get_logger()


class TickerResolver:
    """Resolves ISINs to Yahoo Finance tickers via OpenFIGI.

    Usage::

        async with TickerResolver(api_key="...") as resolver:
            results = await resolver.resolve_batch(["IE00B4L5Y983", ...])
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._external_client = http_client is not None
        self._client = http_client or httpx.AsyncClient(timeout=30.0)

    async def __aenter__(self) -> TickerResolver:
        return self

    async def __aexit__(self, *exc: object) -> None:
        if not self._external_client:
            await self._client.aclose()

    async def resolve_batch(self, isins: list[str]) -> list[IsinResolution]:
        """Resolve a batch of ISINs (up to OPENFIGI_BATCH_SIZE).

        Never raises — unresolved ISINs return resolved_via='unresolved'.
        """
        check_openfigi_rate(has_api_key=bool(self._api_key))
        return await resolve_isin_to_ticker_batch(
            isins,
            http_client=self._client,
            api_key=self._api_key,
        )

    async def resolve_all(
        self,
        isins: list[str],
        *,
        on_batch_complete: Any = None,
    ) -> list[IsinResolution]:
        """Resolve an arbitrarily large list of ISINs in batches.

        Splits into OPENFIGI_BATCH_SIZE chunks, rate-limits between batches.
        Optional callback ``on_batch_complete(batch_num, total_batches, results)``
        for progress tracking.
        """
        all_results: list[IsinResolution] = []
        total_batches = (len(isins) + OPENFIGI_BATCH_SIZE - 1) // OPENFIGI_BATCH_SIZE

        for batch_num, i in enumerate(range(0, len(isins), OPENFIGI_BATCH_SIZE), 1):
            batch = isins[i : i + OPENFIGI_BATCH_SIZE]
            results = await self.resolve_batch(batch)
            all_results.extend(results)

            if on_batch_complete:
                try:
                    on_batch_complete(batch_num, total_batches, results)
                except Exception:
                    pass

            logger.info(
                "ticker_resolver.batch_complete",
                batch=batch_num,
                total=total_batches,
                resolved=sum(1 for r in results if r.is_tradeable),
                unresolved=sum(1 for r in results if not r.is_tradeable),
            )

        resolved_count = sum(1 for r in all_results if r.is_tradeable)
        logger.info(
            "ticker_resolver.complete",
            total_isins=len(isins),
            resolved=resolved_count,
            resolution_rate=f"{resolved_count / len(isins) * 100:.1f}%" if isins else "0%",
        )
        return all_results
