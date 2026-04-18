"""Unit tests for universe_auto_import_service orchestration.

Focuses on the Python-side logic:

* classifier integration — rows with ``block_id is None`` increment
  ``skipped_by_reason`` with the exact reason key,
* metrics aggregation — ``added`` vs ``updated`` derive from the
  ``RETURNING (xmax = 0)`` scalar,
* reject preservation — when the UPSERT returns ``None`` (ON CONFLICT
  hit the WHERE filter on a rejected row), metrics record
  ``respected_reject``,
* statement_timeout + audit event are emitted once per org.

The SQL itself is exercised against a real Postgres by the worker smoke
test (``python -m app.domains.wealth.workers.universe_auto_import``) and
the integration test suite. Here we mock ``db.execute``.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domains.wealth.services.universe_auto_import_service import (
    AUM_FLOOR_USD,
    NAV_COVERAGE_MIN,
    STATEMENT_TIMEOUT_SECONDS,
    auto_import_for_org,
)


def _mock_row(scalar_value: Any) -> MagicMock:
    """Build a mock SQLAlchemy Result that returns ``scalar_value``
    from ``scalar_one_or_none()``.
    """
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar_value
    return result


def _mock_db(upsert_returns: list[Any]) -> tuple[AsyncMock, list]:
    """Build a mock AsyncSession. ``upsert_returns`` is the list of
    values the UPSERT RETURNING scalar should produce in call order
    (True=insert, False=update, None=reject-preserved).

    Returns (db_mock, captured_calls) — the calls list is populated by
    ``db.execute`` with (text_compiled_sql, params) for assertions on
    timeout/audit.
    """
    captured: list[tuple[str, Any]] = []
    upsert_iter = iter(upsert_returns)

    # Pre-seeded allocation_blocks snapshot — covers the strategy_label
    # mappings used in this suite. PR-A23 makes equity / FI fallback
    # paths return None when no valid block is available, so the tests
    # need the classifier's ``valid_blocks`` to actually include the
    # mapped targets.
    _VALID_BLOCKS = [
        ("na_equity_large",), ("na_equity_growth",), ("na_equity_value",),
        ("na_equity_small",), ("dm_europe_equity",), ("dm_asia_equity",),
        ("em_equity",), ("fi_us_aggregate",), ("fi_us_treasury",),
        ("fi_us_tips",), ("fi_us_high_yield",), ("fi_em_debt",),
        ("alt_real_estate",), ("alt_gold",), ("alt_commodities",),
        ("alt_hedge_fund",), ("alt_managed_futures",), ("cash",),
    ]

    async def _execute(stmt: Any, params: dict | None = None) -> MagicMock:
        sql_str = str(stmt)
        captured.append((sql_str, params))
        if "INSERT INTO instruments_org" in sql_str:
            return _mock_row(next(upsert_iter))
        if "statement_timeout" in sql_str:
            return _mock_row(None)
        if "SELECT block_id FROM allocation_blocks" in sql_str:
            res = MagicMock()
            res.all.return_value = _VALID_BLOCKS
            return res
        # audit / misc
        return _mock_row(None)

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=_execute)
    return db, captured


def _inst(
    *,
    asset_class: str = "equity",
    strategy_label: str | None = "Large Blend",
    instrument_type: str = "fund",
    fund_type: str | None = None,
    name: str = "Test Fund",
) -> dict:
    attrs: dict = {}
    if strategy_label is not None:
        attrs["strategy_label"] = strategy_label
    if fund_type is not None:
        attrs["fund_type"] = fund_type
    return {
        "instrument_id": uuid.uuid4(),
        "asset_class": asset_class,
        "instrument_type": instrument_type,
        "name": name,
        "attributes": attrs,
    }


@pytest.mark.asyncio
class TestAutoImportForOrg:
    async def test_all_classified_and_inserted(self) -> None:
        qualified = [
            _inst(strategy_label="Large Blend"),
            _inst(asset_class="fixed_income", strategy_label="High Yield Bond"),
            _inst(asset_class="cash", strategy_label=None),
        ]
        db, _ = _mock_db([True, True, True])
        org_id = uuid.uuid4()

        with patch(
            "app.domains.wealth.services.universe_auto_import_service.write_audit_event",
            new=AsyncMock(),
        ):
            metrics = await auto_import_for_org(
                db, org_id, reason="test", qualified=qualified,
            )

        assert metrics["evaluated"] == 3
        assert metrics["added"] == 3
        assert metrics["updated"] == 0
        assert metrics["skipped"] == 0
        assert metrics["skipped_by_reason"] == {}

    async def test_mixed_insert_update_reject(self) -> None:
        qualified = [
            _inst(strategy_label="Large Blend"),
            _inst(asset_class="fixed_income", strategy_label="High Yield Bond"),
            _inst(strategy_label="Growth"),
        ]
        # First inserts, second updates (existing row), third hit a
        # rejected row (WHERE filter suppressed the UPDATE → no row
        # returned).
        db, _ = _mock_db([True, False, None])
        org_id = uuid.uuid4()

        with patch(
            "app.domains.wealth.services.universe_auto_import_service.write_audit_event",
            new=AsyncMock(),
        ):
            metrics = await auto_import_for_org(
                db, org_id, reason="test", qualified=qualified,
            )

        assert metrics["added"] == 1
        assert metrics["updated"] == 1
        assert metrics["skipped"] == 1
        assert metrics["skipped_by_reason"]["respected_reject"] == 1

    async def test_classifier_skip_tracked_by_reason(self) -> None:
        qualified = [
            _inst(strategy_label="Large Blend"),  # classified → inserted
            _inst(strategy_label="Allocation--50% to 70% Equity"),  # hybrid skip
            _inst(  # private fund skip
                asset_class="alternatives",
                strategy_label=None,
                fund_type="Hedge Fund",
            ),
            _inst(asset_class="other", instrument_type="unknown", strategy_label=None),
        ]
        db, _ = _mock_db([True])  # only one UPSERT — the classified row
        org_id = uuid.uuid4()

        with patch(
            "app.domains.wealth.services.universe_auto_import_service.write_audit_event",
            new=AsyncMock(),
        ):
            metrics = await auto_import_for_org(
                db, org_id, reason="test", qualified=qualified,
            )

        assert metrics["added"] == 1
        assert metrics["skipped"] == 3
        assert metrics["skipped_by_reason"]["hybrid_unsupported"] == 1
        assert metrics["skipped_by_reason"]["private_fund_type"] == 1
        assert metrics["skipped_by_reason"]["unclassified"] == 1

    async def test_statement_timeout_issued_once(self) -> None:
        qualified = [_inst()]
        db, captured = _mock_db([True])
        org_id = uuid.uuid4()

        with patch(
            "app.domains.wealth.services.universe_auto_import_service.write_audit_event",
            new=AsyncMock(),
        ):
            await auto_import_for_org(
                db, org_id, reason="test", qualified=qualified,
            )

        timeout_calls = [c for c in captured if "statement_timeout" in c[0]]
        assert len(timeout_calls) == 1
        assert f"{STATEMENT_TIMEOUT_SECONDS}s" in timeout_calls[0][0]

    async def test_audit_event_fires_once_with_metrics(self) -> None:
        qualified = [_inst(), _inst(strategy_label="Growth")]
        db, _ = _mock_db([True, True])
        org_id = uuid.uuid4()

        audit_mock = AsyncMock()
        with patch(
            "app.domains.wealth.services.universe_auto_import_service.write_audit_event",
            new=audit_mock,
        ):
            metrics = await auto_import_for_org(
                db, org_id, reason="org_provisioning", qualified=qualified,
                actor_id="admin:abc", actor_roles=["SUPER_ADMIN"],
                request_id="req-123",
            )

        assert audit_mock.await_count == 1
        call_kwargs = audit_mock.await_args.kwargs
        assert call_kwargs["action"] == "auto_import"
        assert call_kwargs["entity_type"] == "instruments_org"
        assert call_kwargs["entity_id"] == str(org_id)
        assert call_kwargs["actor_id"] == "admin:abc"
        assert call_kwargs["actor_roles"] == ["SUPER_ADMIN"]
        assert call_kwargs["request_id"] == "req-123"
        assert call_kwargs["organization_id"] == org_id
        after = call_kwargs["after"]
        assert after["reason"] == "org_provisioning"
        assert after["aum_floor_usd"] == AUM_FLOOR_USD
        assert after["nav_coverage_min"] == NAV_COVERAGE_MIN
        assert after["added"] == metrics["added"]

    async def test_pr_a23_needs_human_review_flags_universe(self) -> None:
        """PR-A23: when the classifier surfaces a previously-silent
        fallback case, the service must (a) count under
        ``skipped_by_reason["needs_human_review"]`` and (b) issue an
        UPDATE against ``instruments_universe`` to flag the row.
        """
        qualified = [
            _inst(strategy_label=None, asset_class="fixed_income",
                  name="PIMCO Total Return"),
        ]
        db, captured = _mock_db([])  # no UPSERT expected
        org_id = uuid.uuid4()

        with patch(
            "app.domains.wealth.services.universe_auto_import_service.write_audit_event",
            new=AsyncMock(),
        ):
            metrics = await auto_import_for_org(
                db, org_id, reason="test", qualified=qualified,
            )

        assert metrics["added"] == 0
        assert metrics["skipped"] == 1
        assert metrics["skipped_by_reason"]["needs_human_review"] == 1

        flag_updates = [
            c for c in captured
            if "UPDATE instruments_universe" in c[0]
            and "needs_human_review" in c[0]
        ]
        assert len(flag_updates) == 1

    async def test_qualified_none_triggers_fetch(self) -> None:
        """When callers pass qualified=None, the service fetches the
        global rowset inline. Here we assert ``_fetch_qualified_instruments``
        is called exactly once and its result is iterated.
        """
        db, _ = _mock_db([True])
        org_id = uuid.uuid4()

        fetch_mock = AsyncMock(return_value=[_inst()])
        with patch(
            "app.domains.wealth.services.universe_auto_import_service.fetch_qualified_instruments",
            new=fetch_mock,
        ), patch(
            "app.domains.wealth.services.universe_auto_import_service.write_audit_event",
            new=AsyncMock(),
        ):
            metrics = await auto_import_for_org(
                db, org_id, reason="ad_hoc",
            )

        assert fetch_mock.await_count == 1
        assert metrics["evaluated"] == 1
        assert metrics["added"] == 1
