"""Market Data — WebSocket live feed + REST snapshot + portfolio holdings + screener catalog.

WebSocket endpoint: ``/api/v1/market-data/live/ws?token=<jwt>``
REST endpoints:
  - ``/api/v1/market-data/dashboard-snapshot``
  - ``/api/v1/market-data/portfolio/{portfolio_id}/holdings``
  - ``/api/v1/market-data/screener/catalog``

Architecture:
  - Workers publish price ticks to Redis ``market:prices`` channel.
  - WebSocket connections subscribe to that channel via ConnectionManager.
  - REST endpoints read from DB only (DB-first, zero API calls).

JWT auth: WebSocket uses query param (``?token=``); REST uses standard Bearer header.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from decimal import Decimal

import orjson
from fastapi import APIRouter, Depends, Path, Query, Request, WebSocket, WebSocketDisconnect
from sqlalchemy import case as sa_case
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.clerk_auth import Actor, get_actor
from app.core.tenancy.middleware import get_db_with_rls
from app.core.ws.auth import authenticate_ws
from app.core.ws.manager import HEARTBEAT_INTERVAL, ConnectionManager
from app.core.ws.tiingo_bridge import TiingoStreamBridge
from app.domains.wealth.schemas.market_data import (
    DashboardSnapshot,
    HistoricalResponse,
    NewsItem,
    NewsResponse,
    OHLCVBar,
    PortfolioHoldingsResponse,
    PortfolioHoldingSummary,
    Position,
    ScreenerAsset,
    ScreenerAssetPage,
    WsServerMessage,
)
from app.services.providers.tiingo_provider import get_tiingo_provider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/market-data", tags=["market-data"])


def _get_manager(request_or_ws: Request | WebSocket) -> ConnectionManager:
    """Retrieve the ConnectionManager from app state."""
    return request_or_ws.app.state.ws_manager


def _get_bridge(ws: WebSocket) -> TiingoStreamBridge:
    """Retrieve the TiingoStreamBridge from app state."""
    return ws.app.state.tiingo_bridge


# ── WebSocket Endpoint ──────────────────────────────────────


@router.websocket("/live/ws")
async def market_data_ws(ws: WebSocket):
    """Real-time market data WebSocket.

    Protocol:
      1. Connect with ``?token=<jwt>`` query param.
      2. Send ``{"action": "subscribe", "tickers": ["SPY", "QQQ"]}``
      3. Receive ``{"type": "price", "data": {...}}`` for each matching tick.
      4. Send ``{"action": "ping"}`` → receive ``{"type": "pong"}``.
      5. Send ``{"action": "unsubscribe", "tickers": ["SPY"]}`` to stop tickers.

    Close codes:
      - 1008: Authentication failed (missing/invalid/expired token).
      - 1000: Normal close.
    """
    # Authenticate before accepting
    actor = await authenticate_ws(ws)
    if actor is None:
        return  # Socket already closed by authenticate_ws

    manager = _get_manager(ws)
    bridge = _get_bridge(ws)
    conn = await manager.accept(ws, actor)
    conn_id = conn.conn_id

    # Send confirmation
    await manager.send_personal(conn_id, WsServerMessage(
        type="subscribed",
        data={"message": "Connected", "tickers": []},
    ).model_dump())

    # Heartbeat task — ping every 15s. Routed through the manager so
    # it shares the per-connection outbound channel with everything
    # else (no direct ws.send_bytes — that would bypass the bounded
    # queue and the slow-consumer eviction policy).
    async def heartbeat():
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                await manager.send_personal(conn_id, WsServerMessage(
                    type="pong",
                    data=None,
                ).model_dump())
        except Exception:
            pass

    heartbeat_task = asyncio.create_task(heartbeat())

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = orjson.loads(raw)
            except (orjson.JSONDecodeError, ValueError):
                await manager.send_personal(conn_id, WsServerMessage(
                    type="error",
                    data={"message": "Invalid JSON"},
                ).model_dump())
                continue

            action = msg.get("action")

            if action == "subscribe":
                tickers = msg.get("tickers", [])
                if not isinstance(tickers, list) or len(tickers) == 0:
                    await manager.send_personal(conn_id, WsServerMessage(
                        type="error",
                        data={"message": "tickers must be a non-empty list"},
                    ).model_dump())
                    continue
                # Normalize to uppercase
                normalized = {t.upper() for t in tickers if isinstance(t, str)}
                # Merge with existing subscriptions
                current = conn.tickers | normalized
                manager.update_subscriptions(conn_id, current)
                # Also subscribe on Tiingo WS for live IEX prices
                await bridge.subscribe(list(normalized))
                await manager.send_personal(conn_id, WsServerMessage(
                    type="subscribed",
                    data={"tickers": sorted(current)},
                ).model_dump())

            elif action == "unsubscribe":
                tickers = msg.get("tickers", [])
                normalized = {t.upper() for t in tickers if isinstance(t, str)}
                current = conn.tickers - normalized
                manager.update_subscriptions(conn_id, current)
                await bridge.unsubscribe(list(normalized))
                await manager.send_personal(conn_id, WsServerMessage(
                    type="subscribed",
                    data={"tickers": sorted(current)},
                ).model_dump())

            elif action == "ping":
                await manager.send_personal(conn_id, WsServerMessage(
                    type="pong",
                    data=None,
                ).model_dump())

            else:
                await manager.send_personal(conn_id, WsServerMessage(
                    type="error",
                    data={"message": f"Unknown action: {action}"},
                ).model_dump())

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("ws_unexpected_error actor=%s", actor.actor_id)
    finally:
        heartbeat_task.cancel()
        await manager.disconnect(conn_id)


# ── REST: Dashboard Snapshot ────────────────────────────────


@router.get(
    "/dashboard-snapshot",
    response_model=DashboardSnapshot,
    summary="Dashboard initial data — portfolio holdings with latest prices",
)
async def dashboard_snapshot(
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db_with_rls),
):
    """Load the org's active model portfolio holdings with latest NAV prices.

    Source: ``model_portfolios.fund_selection_schema`` (weights) + ``nav_timeseries``
    (latest prices). Positions use allocation weights, not unit counts.

    Reads from DB only — zero external API calls (DB-first pattern).
    """
    from app.domains.wealth.models.model_portfolio import ModelPortfolio

    # 1. Find the org's active model portfolio (any profile, prefer active)
    portfolio_stmt = (
        select(ModelPortfolio)
        .where(ModelPortfolio.status.in_(["active", "draft"]))
        .order_by(
            # Prefer 'active' over 'draft'
            sa_case((ModelPortfolio.status == "active", 0), else_=1),
            ModelPortfolio.created_at.desc(),
        )
        .limit(1)
    )
    portfolio_result = await db.execute(portfolio_stmt)
    portfolio = portfolio_result.scalar_one_or_none()

    if not portfolio or not portfolio.fund_selection_schema:
        # Fallback: show approved instruments without weight data
        return await _fallback_approved_instruments(db)

    funds = portfolio.fund_selection_schema.get("funds", [])
    if not funds:
        return await _fallback_approved_instruments(db)

    # 2. Extract instrument_id → weight map
    weight_map: dict[str, Decimal] = {}
    for f in funds:
        iid = f.get("instrument_id")
        w = f.get("weight")
        if iid and w:
            weight_map[str(iid)] = Decimal(str(w))

    instrument_ids = list(weight_map.keys())
    if not instrument_ids:
        return await _fallback_approved_instruments(db)

    # 3. Query instruments + latest NAV in one shot
    placeholders = ", ".join(f"'{iid}'" for iid in instrument_ids)
    query = text(f"""
        WITH latest_nav AS (
            SELECT DISTINCT ON (instrument_id)
                instrument_id,
                nav_date,
                nav,
                return_1d,
                aum_usd,
                currency,
                source
            FROM nav_timeseries
            WHERE instrument_id::text IN ({placeholders})
            ORDER BY instrument_id, nav_date DESC
        ),
        prev_nav AS (
            SELECT DISTINCT ON (nt.instrument_id)
                nt.instrument_id,
                nt.nav AS prev_nav
            FROM nav_timeseries nt
            JOIN latest_nav ln ON ln.instrument_id = nt.instrument_id
                AND nt.nav_date < ln.nav_date
            ORDER BY nt.instrument_id, nt.nav_date DESC
        )
        SELECT
            iu.instrument_id,
            iu.ticker,
            iu.name,
            COALESCE(ln.nav, 0) AS price,
            COALESCE(ln.nav - pn.prev_nav, 0) AS change,
            CASE
                WHEN pn.prev_nav IS NOT NULL AND pn.prev_nav != 0
                THEN ((ln.nav - pn.prev_nav) / pn.prev_nav * 100)
                ELSE 0
            END AS change_pct,
            ln.aum_usd,
            iu.asset_class,
            COALESCE(ln.currency, iu.currency, 'USD') AS currency,
            ln.nav_date
        FROM instruments_universe iu
        LEFT JOIN latest_nav ln ON ln.instrument_id = iu.instrument_id
        LEFT JOIN prev_nav pn ON pn.instrument_id = iu.instrument_id
        WHERE iu.instrument_id::text IN ({placeholders})
        ORDER BY COALESCE(ln.aum_usd, 0) DESC
    """)

    result = await db.execute(query)
    rows = result.mappings().all()

    # 4. Build holdings with weight as allocation percentage
    holdings: list[PortfolioHoldingSummary] = []
    total_aum = Decimal("0")
    latest_date: date | None = None
    for row in rows:
        iid = str(row["instrument_id"])
        weight = weight_map.get(iid, Decimal("0"))
        price = Decimal(str(row["price"])) if row["price"] else Decimal("0")
        aum = Decimal(str(row["aum_usd"])) if row["aum_usd"] else None

        holdings.append(PortfolioHoldingSummary(
            instrument_id=iid,
            ticker=row["ticker"] or "",
            name=row["name"] or "",
            price=price,
            change=Decimal(str(row["change"])) if row["change"] else Decimal("0"),
            change_pct=Decimal(str(row["change_pct"])) if row["change_pct"] else Decimal("0"),
            weight=weight,
            aum_usd=aum,
            asset_class=row["asset_class"] or "",
            currency=row["currency"] or "USD",
        ))

        if aum:
            total_aum += aum
        if row.get("nav_date") and (latest_date is None or row["nav_date"] > latest_date):
            latest_date = row["nav_date"]

    # 5. Enrich holdings with zero prices from Tiingo REST
    holdings = await _enrich_missing_prices(holdings)

    # 6. Total return = weighted sum of individual changes
    total_return: Decimal | None = None
    if holdings:
        weighted_sum = sum(h.change_pct * h.weight for h in holdings)
        total_return = weighted_sum

    return DashboardSnapshot(
        holdings=holdings,
        total_aum=total_aum,
        total_return_pct=total_return,
        as_of=(latest_date.isoformat() if latest_date else datetime.utcnow().date().isoformat()),
    )


async def _fallback_approved_instruments(
    db: AsyncSession,
) -> DashboardSnapshot:
    """Fallback when no model portfolio exists — show approved instruments."""
    query = text("""
        WITH latest_nav AS (
            SELECT DISTINCT ON (instrument_id)
                instrument_id, nav_date, nav, aum_usd, currency
            FROM nav_timeseries
            ORDER BY instrument_id, nav_date DESC
        )
        SELECT
            iu.instrument_id, iu.ticker, iu.name,
            COALESCE(ln.nav, 0) AS price,
            ln.aum_usd, iu.asset_class,
            COALESCE(ln.currency, iu.currency, 'USD') AS currency,
            ln.nav_date
        FROM instruments_org io
        JOIN instruments_universe iu ON iu.instrument_id = io.instrument_id
        LEFT JOIN latest_nav ln ON ln.instrument_id = iu.instrument_id
        WHERE io.approval_status = 'approved'
        ORDER BY COALESCE(ln.aum_usd, 0) DESC
        LIMIT 50
    """)
    result = await db.execute(query)
    rows = result.mappings().all()

    holdings: list[PortfolioHoldingSummary] = []
    total_aum = Decimal("0")
    latest_date: date | None = None

    for row in rows:
        price = Decimal(str(row["price"])) if row["price"] else Decimal("0")
        aum = Decimal(str(row["aum_usd"])) if row["aum_usd"] else None
        holdings.append(PortfolioHoldingSummary(
            instrument_id=str(row["instrument_id"]),
            ticker=row["ticker"] or "",
            name=row["name"] or "",
            price=price,
            change=Decimal("0"),
            change_pct=Decimal("0"),
            weight=Decimal("0"),
            aum_usd=aum,
            asset_class=row["asset_class"] or "",
            currency=row["currency"] or "USD",
        ))
        if aum:
            total_aum += aum
        if row.get("nav_date") and (latest_date is None or row["nav_date"] > latest_date):
            latest_date = row["nav_date"]

    # Enrich holdings with zero prices from Tiingo REST (fallback for empty nav_timeseries)
    holdings = await _enrich_missing_prices(holdings)

    return DashboardSnapshot(
        holdings=holdings,
        total_aum=total_aum,
        total_return_pct=None,
        as_of=(latest_date.isoformat() if latest_date else datetime.utcnow().date().isoformat()),
    )


async def _enrich_missing_prices(
    holdings: list[PortfolioHoldingSummary],
) -> list[PortfolioHoldingSummary]:
    """Fetch latest prices from Tiingo REST for holdings with price == 0.

    Called when nav_timeseries has no data for some instruments (e.g., newly
    approved funds before the instrument_ingestion worker runs).
    Non-blocking: failures are silently skipped — the holding stays at $0.
    """
    import httpx

    from app.core.config.settings import settings as _settings

    api_key = _settings.tiingo_api_key
    if not api_key:
        return holdings

    missing = [(i, h) for i, h in enumerate(holdings) if h.price == 0 and h.ticker]
    if not missing:
        return holdings

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Token {api_key}",
    }

    # Institutional plan: 10k req/h. Fan out concurrently with a generous
    # cap — old free-tier serial loop was throughput-bound, not rate-bound.
    sem = asyncio.Semaphore(50)

    async with httpx.AsyncClient(timeout=10) as client:
        async def _fetch_one(idx: int, h: PortfolioHoldingSummary) -> None:
            async with sem:
                try:
                    resp = await client.get(
                        f"https://api.tiingo.com/tiingo/daily/{h.ticker}/prices",
                        headers=headers,
                    )
                    if resp.status_code != 200:
                        return
                    rows_data = resp.json()
                    if not rows_data:
                        return
                    last = rows_data[-1]
                    close_price = Decimal(
                        str(last.get("adjClose") or last.get("close", 0)),
                    )
                    if close_price > 0:
                        holdings[idx] = h.model_copy(
                            update={
                                "price": close_price,
                                "change": Decimal("0"),
                                "change_pct": Decimal("0"),
                            },
                        )
                except Exception:
                    return

        await asyncio.gather(*(_fetch_one(i, h) for i, h in missing))

    return holdings


# ── REST: Portfolio Holdings ───────────────────────────────


@router.get(
    "/portfolio/{portfolio_id}/holdings",
    response_model=PortfolioHoldingsResponse,
    summary="Portfolio positions with cost basis and latest pricing",
)
async def portfolio_holdings(
    portfolio_id: str = Path(..., description="Model portfolio ID (UUID) or profile name"),
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db_with_rls),
) -> PortfolioHoldingsResponse:
    """Return detailed positions for a model portfolio.

    Each position includes weight, notional quantity, cost basis,
    last price, and previous close — all fields needed for the
    frontend to compute real-time P&L when fused with WS price ticks.

    Reads from DB only (DB-first pattern).
    """
    from app.domains.wealth.models.model_portfolio import ModelPortfolio

    # Resolve by UUID or profile name
    portfolio_stmt = select(ModelPortfolio).where(
        ModelPortfolio.status.in_(["active", "draft"]),
    )
    # Try UUID first, fallback to profile name
    try:
        import uuid as _uuid
        _uuid.UUID(portfolio_id)
        portfolio_stmt = portfolio_stmt.where(
            ModelPortfolio.portfolio_id == portfolio_id,
        )
    except ValueError:
        portfolio_stmt = portfolio_stmt.where(
            ModelPortfolio.profile == portfolio_id,
        )

    portfolio_stmt = portfolio_stmt.order_by(
        sa_case((ModelPortfolio.status == "active", 0), else_=1),
        ModelPortfolio.created_at.desc(),
    ).limit(1)

    result = await db.execute(portfolio_stmt)
    portfolio = result.scalar_one_or_none()

    if not portfolio or not portfolio.fund_selection_schema:
        return PortfolioHoldingsResponse(
            portfolio_id=portfolio_id,
            profile=getattr(portfolio, "profile", portfolio_id),
            holdings=[],
            cash_balance=Decimal("0"),
            portfolio_nav=Decimal("0"),
            as_of=datetime.utcnow().date().isoformat(),
        )

    funds = portfolio.fund_selection_schema.get("funds", [])
    weight_map: dict[str, Decimal] = {}
    for f in funds:
        iid = f.get("instrument_id")
        w = f.get("weight")
        if iid and w:
            weight_map[str(iid)] = Decimal(str(w))

    instrument_ids = list(weight_map.keys())
    if not instrument_ids:
        return PortfolioHoldingsResponse(
            portfolio_id=str(portfolio.portfolio_id),
            profile=portfolio.profile,
            holdings=[],
            cash_balance=Decimal("0"),
            portfolio_nav=Decimal("0"),
            as_of=datetime.utcnow().date().isoformat(),
        )

    # Query instruments + latest + previous NAV
    placeholders = ", ".join(f"'{iid}'" for iid in instrument_ids)
    query = text(f"""
        WITH latest_nav AS (
            SELECT DISTINCT ON (instrument_id)
                instrument_id, nav_date, nav, aum_usd, currency
            FROM nav_timeseries
            WHERE instrument_id::text IN ({placeholders})
            ORDER BY instrument_id, nav_date DESC
        ),
        prev_nav AS (
            SELECT DISTINCT ON (nt.instrument_id)
                nt.instrument_id, nt.nav AS prev_nav
            FROM nav_timeseries nt
            JOIN latest_nav ln ON ln.instrument_id = nt.instrument_id
                AND nt.nav_date < ln.nav_date
            ORDER BY nt.instrument_id, nt.nav_date DESC
        )
        SELECT
            iu.instrument_id, iu.ticker, iu.name,
            iu.asset_class,
            COALESCE(ln.currency, iu.currency, 'USD') AS currency,
            COALESCE(ln.nav, 0) AS last_price,
            COALESCE(pn.prev_nav, ln.nav, 0) AS previous_close,
            ln.aum_usd,
            ln.nav_date
        FROM instruments_universe iu
        LEFT JOIN latest_nav ln ON ln.instrument_id = iu.instrument_id
        LEFT JOIN prev_nav pn ON pn.instrument_id = iu.instrument_id
        WHERE iu.instrument_id::text IN ({placeholders})
        ORDER BY COALESCE(ln.aum_usd, 0) DESC
    """)

    rows = (await db.execute(query)).mappings().all()

    # Compute a synthetic portfolio NAV for notional quantity calculation
    portfolio_nav = Decimal(
        str(portfolio.fund_selection_schema.get("portfolio_nav", "1000000")),
    )
    cash_balance = Decimal(
        str(portfolio.fund_selection_schema.get("cash_balance", "0")),
    )

    positions: list[Position] = []
    latest_date: date | None = None
    for row in rows:
        iid = str(row["instrument_id"])
        weight = weight_map.get(iid, Decimal("0"))
        last_price = Decimal(str(row["last_price"])) if row["last_price"] else Decimal("0")
        prev_close = Decimal(str(row["previous_close"])) if row["previous_close"] else Decimal("0")
        aum = Decimal(str(row["aum_usd"])) if row["aum_usd"] else None

        # Notional quantity: how many "units" this weight represents
        quantity = (weight * portfolio_nav / last_price) if last_price > 0 else Decimal("0")

        positions.append(Position(
            instrument_id=iid,
            ticker=row["ticker"] or "",
            name=row["name"] or "",
            asset_class=row["asset_class"] or "",
            currency=row["currency"] or "USD",
            weight=weight,
            quantity=quantity.quantize(Decimal("0.0001")),
            avg_cost=prev_close,  # Use previous close as cost basis proxy
            last_price=last_price,
            previous_close=prev_close,
            price_date=row["nav_date"].isoformat() if row.get("nav_date") else None,
            aum_usd=aum,
        ))

        if row.get("nav_date") and (latest_date is None or row["nav_date"] > latest_date):
            latest_date = row["nav_date"]

    return PortfolioHoldingsResponse(
        portfolio_id=str(portfolio.portfolio_id),
        profile=portfolio.profile,
        holdings=positions,
        cash_balance=cash_balance,
        portfolio_nav=portfolio_nav,
        as_of=(latest_date.isoformat() if latest_date else datetime.utcnow().date().isoformat()),
    )


# ── REST: Screener Asset Catalog ───────────────────────────


@router.get(
    "/screener/catalog",
    response_model=ScreenerAssetPage,
    summary="Paginated asset catalog with latest prices for live screener",
)
async def screener_catalog(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Items per page"),
    q: str = Query("", description="Search query (name or ticker)"),
    asset_class: str = Query("", description="Filter by asset class"),
    region: str = Query("", description="Filter by region (US/EU)"),
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db_with_rls),
) -> ScreenerAssetPage:
    """Paginated asset catalog for the live screener grid.

    Returns static metadata + latest price/change from ``nav_timeseries``.
    The frontend subscribes to tickers from the current page via WebSocket
    for live updates; this endpoint provides the SSR seed.

    Reads from ``mv_unified_funds`` materialized view + ``nav_timeseries``.
    """
    offset = (page - 1) * page_size

    # Build WHERE clauses
    where_clauses: list[str] = []
    if q:
        where_clauses.append(
            "(LOWER(f.name) LIKE :q_pattern OR LOWER(COALESCE(f.ticker, '')) LIKE :q_pattern)"
        )
    if asset_class:
        where_clauses.append("f.fund_type = :asset_class")
    if region:
        where_clauses.append("f.region = :region")

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    # Count total
    count_query = text(f"""
        SELECT COUNT(*) FROM mv_unified_funds f {where_sql}
    """)

    # Main query with latest pricing
    data_query = text(f"""
        WITH latest_nav AS (
            SELECT DISTINCT ON (instrument_id)
                instrument_id, nav, nav_date, aum_usd,
                return_1d
            FROM nav_timeseries
            ORDER BY instrument_id, nav_date DESC
        ),
        prev_nav AS (
            SELECT DISTINCT ON (nt.instrument_id)
                nt.instrument_id, nt.nav AS prev_nav
            FROM nav_timeseries nt
            JOIN latest_nav ln ON ln.instrument_id = nt.instrument_id
                AND nt.nav_date < ln.nav_date
            ORDER BY nt.instrument_id, nt.nav_date DESC
        )
        SELECT
            f.external_id,
            f.ticker,
            f.name,
            f.fund_type AS asset_class,
            f.region,
            f.fund_type,
            f.strategy_label,
            f.currency,
            f.aum,
            f.expense_ratio_pct,
            f.inception_date,
            ln.nav AS last_price,
            COALESCE(ln.nav - pn.prev_nav, 0) AS change,
            CASE
                WHEN pn.prev_nav IS NOT NULL AND pn.prev_nav != 0
                THEN ((ln.nav - pn.prev_nav) / pn.prev_nav * 100)
                ELSE 0
            END AS change_pct
        FROM mv_unified_funds f
        LEFT JOIN instruments_universe iu ON iu.ticker = f.ticker AND f.ticker IS NOT NULL
        LEFT JOIN latest_nav ln ON ln.instrument_id = iu.instrument_id
        LEFT JOIN prev_nav pn ON pn.instrument_id = iu.instrument_id
        {where_sql}
        ORDER BY COALESCE(f.aum, 0) DESC
        LIMIT :page_size OFFSET :offset
    """)

    # Build params
    params: dict[str, str | int] = {"page_size": page_size, "offset": offset}
    if q:
        params["q_pattern"] = f"%{q.lower()}%"
    if asset_class:
        params["asset_class"] = asset_class
    if region:
        params["region"] = region

    total_result = await db.execute(count_query, params)
    total = total_result.scalar() or 0

    data_result = await db.execute(data_query, params)
    rows = data_result.mappings().all()

    items: list[ScreenerAsset] = []
    for row in rows:
        items.append(ScreenerAsset(
            external_id=str(row["external_id"]),
            ticker=row["ticker"],
            name=row["name"] or "",
            asset_class=row["asset_class"] or "",
            region=row["region"] or "",
            fund_type=row["fund_type"] or "",
            strategy_label=row.get("strategy_label"),
            currency=row.get("currency"),
            aum=Decimal(str(row["aum"])) if row.get("aum") else None,
            expense_ratio_pct=Decimal(str(row["expense_ratio_pct"])) if row.get("expense_ratio_pct") else None,
            inception_date=row["inception_date"].isoformat() if row.get("inception_date") else None,
            last_price=Decimal(str(row["last_price"])) if row.get("last_price") else None,
            change=Decimal(str(row["change"])) if row.get("change") is not None else None,
            change_pct=Decimal(str(row["change_pct"])) if row.get("change_pct") is not None else None,
        ))

    return ScreenerAssetPage(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        has_next=(page * page_size < total),
    )


# ── REST: News Feed (Tiingo) ───────────────────────────────


@router.get(
    "/news",
    response_model=NewsResponse,
    summary="Editorial news feed (Tiingo News) — optionally filtered by tickers",
)
async def market_news(
    tickers: str = Query(
        "",
        description="Comma-separated ticker filter (e.g. 'AAPL,MSFT'). Empty = full firehose.",
    ),
    limit: int = Query(20, ge=1, le=200, description="Max articles to return"),
    actor: Actor = Depends(get_actor),
) -> NewsResponse:
    """Fetch the latest news headlines from Tiingo's editorial feed.

    No DB cache yet — Tiingo News is the source of truth and the
    institutional plan rate limit (10k req/h) accommodates the dashboard
    polling cadence (typ. 1 req / minute / client).
    """
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()] if tickers else None

    provider = get_tiingo_provider()
    raw_items = await provider.fetch_news(tickers=ticker_list, limit=limit)

    items = [NewsItem.model_validate(it) for it in raw_items]
    return NewsResponse(items=items, count=len(items))


# ── REST: Historical OHLCV (Tiingo) ────────────────────────


@router.get(
    "/historical/{ticker}",
    response_model=HistoricalResponse,
    summary="OHLCV bars for a single ticker (daily or intraday) — Tiingo",
)
async def market_historical(
    ticker: str = Path(..., description="Ticker symbol (e.g. SPY, AAPL)"),
    interval: str = Query(
        "daily",
        description="Bar resolution: daily, 1min, 5min, 15min, 30min, 1hour, 4hour",
    ),
    start_date: str | None = Query(
        None,
        description="ISO date (YYYY-MM-DD). Defaults to last 6 months for daily, last 5 days for intraday.",
    ),
    end_date: str | None = Query(None, description="ISO date (YYYY-MM-DD). Defaults to today."),
    actor: Actor = Depends(get_actor),
) -> HistoricalResponse:
    """Fetch OHLCV history used by the AdvancedMarketChart candlestick view.

    The frontend seeds the chart with this REST snapshot, then folds live
    Tiingo IEX trade ticks into the rightmost candle via the existing
    market-data WebSocket store. Mutual funds (no IEX listing) only return
    data on the ``daily`` interval.
    """
    ticker_norm = ticker.strip().upper()
    if not ticker_norm:
        return HistoricalResponse(ticker=ticker, interval=interval, bars=[])

    # Defaults — keep payloads bounded to avoid blowing the chart
    today = datetime.utcnow().date()
    parsed_start: date | None = None
    parsed_end: date | None = None
    try:
        parsed_start = date.fromisoformat(start_date) if start_date else None
        parsed_end = date.fromisoformat(end_date) if end_date else None
    except ValueError:
        parsed_start = None
        parsed_end = None

    if parsed_end is None:
        parsed_end = today

    if parsed_start is None:
        if interval == "daily":
            parsed_start = parsed_end.replace(year=parsed_end.year - 1) \
                if parsed_end.month != 2 or parsed_end.day != 29 \
                else parsed_end.replace(year=parsed_end.year - 1, day=28)
        else:
            from datetime import timedelta as _td
            parsed_start = parsed_end - _td(days=5)

    provider = get_tiingo_provider()
    if interval == "daily":
        raw_bars = await provider.fetch_historical_daily(
            ticker_norm, start_date=parsed_start, end_date=parsed_end,
        )
    else:
        raw_bars = await provider.fetch_historical_intraday(
            ticker_norm,
            start_date=parsed_start,
            end_date=parsed_end,
            resample_freq=interval,
        )

    bars: list[OHLCVBar] = []
    for b in raw_bars:
        # Skip incomplete bars (Tiingo occasionally returns nulls on holidays)
        if b.get("open") is None or b.get("close") is None:
            continue
        bars.append(OHLCVBar(
            timestamp=b["timestamp"],
            open=Decimal(str(b["open"])),
            high=Decimal(str(b["high"])) if b.get("high") is not None else Decimal(str(b["close"])),
            low=Decimal(str(b["low"])) if b.get("low") is not None else Decimal(str(b["open"])),
            close=Decimal(str(b["close"])),
            volume=Decimal(str(b.get("volume") or 0)),
        ))

    return HistoricalResponse(
        ticker=ticker_norm,
        interval=interval,
        bars=bars,
        source="tiingo",
    )
