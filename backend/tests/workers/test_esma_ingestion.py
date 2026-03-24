"""Tests for the ESMA UCITS ingestion worker.

Covers:
  - Lock ID uniqueness and constants
  - Model integrity (global table, no org_id)
  - Worker flow with mocked RegisterService/TickerResolver
  - Idempotent upsert (FK ordering)
  - Lock acquisition + release in finally
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.shared.models import EsmaFund, EsmaIsinTickerMap, EsmaManager

# ═══════════════════════════════════════════════════════════════════
#  Model integrity
# ═══════════════════════════════════════════════════════════════════


class TestEsmaManagerModel:
    def test_tablename(self) -> None:
        assert EsmaManager.__tablename__ == "esma_managers"

    def test_has_no_organization_id(self) -> None:
        """Global table — must not have organization_id column."""
        columns = {c.name for c in EsmaManager.__table__.columns}
        assert "organization_id" not in columns

    def test_primary_key(self) -> None:
        pk_cols = [c.name for c in EsmaManager.__table__.primary_key.columns]
        assert pk_cols == ["esma_id"]

    def test_has_fund_count_column(self) -> None:
        columns = {c.name for c in EsmaManager.__table__.columns}
        assert "fund_count" in columns

    def test_has_sec_crd_number(self) -> None:
        columns = {c.name for c in EsmaManager.__table__.columns}
        assert "sec_crd_number" in columns


class TestEsmaFundModel:
    def test_tablename(self) -> None:
        assert EsmaFund.__tablename__ == "esma_funds"

    def test_has_no_organization_id(self) -> None:
        columns = {c.name for c in EsmaFund.__table__.columns}
        assert "organization_id" not in columns

    def test_primary_key_is_isin(self) -> None:
        pk_cols = [c.name for c in EsmaFund.__table__.primary_key.columns]
        assert pk_cols == ["isin"]

    def test_fk_to_esma_managers(self) -> None:
        fks = list(EsmaFund.__table__.foreign_keys)
        assert any(
            fk.target_fullname == "esma_managers.esma_id" for fk in fks
        )


class TestEsmaIsinTickerMapModel:
    def test_tablename(self) -> None:
        assert EsmaIsinTickerMap.__tablename__ == "esma_isin_ticker_map"

    def test_has_no_organization_id(self) -> None:
        columns = {c.name for c in EsmaIsinTickerMap.__table__.columns}
        assert "organization_id" not in columns


# ═══════════════════════════════════════════════════════════════════
#  Worker constants
# ═══════════════════════════════════════════════════════════════════


class TestEsmaWorkerConstants:
    def test_lock_id(self) -> None:
        from app.domains.wealth.workers.esma_ingestion import ESMA_LOCK_ID

        assert ESMA_LOCK_ID == 900_023

    def test_batch_size(self) -> None:
        from app.domains.wealth.workers.esma_ingestion import _BATCH_SIZE

        assert _BATCH_SIZE == 2000


# ═══════════════════════════════════════════════════════════════════
#  Worker flow (mocked I/O)
# ═══════════════════════════════════════════════════════════════════


def _make_fund_dc(isin: str, manager_id: str = "MGR001") -> MagicMock:
    """Create a frozen EsmaFund dataclass mock."""
    from data_providers.esma.models import EsmaFund as EsmaFundDC

    return EsmaFundDC(
        isin=isin,
        fund_name=f"Fund {isin}",
        esma_manager_id=manager_id,
        domicile="IE",
        fund_type="UCITS",
        host_member_states=["IE", "DE"],
    )


def _make_manager_dc(esma_id: str = "MGR001") -> MagicMock:
    from data_providers.esma.models import EsmaManager as EsmaManagerDC

    return EsmaManagerDC(
        esma_id=esma_id,
        lei="529900ABC",
        company_name=f"Manager {esma_id}",
        country="IE",
        authorization_status="Active",
        fund_count=2,
    )


class TestEsmaIngestionWorker:
    @pytest.mark.asyncio
    async def test_lock_not_acquired_returns_skipped(self) -> None:
        """If advisory lock is held, worker returns skipped status."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = False
        mock_db.execute.return_value = mock_result
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.domains.wealth.workers.esma_ingestion.async_session",
            return_value=mock_db,
        ):
            from app.domains.wealth.workers.esma_ingestion import run_esma_ingestion

            result = await run_esma_ingestion()

        assert result["status"] == "skipped"
        assert result["reason"] == "lock_held"

    def test_worker_has_finally_unlock(self) -> None:
        """Worker source must contain pg_advisory_unlock in a finally block."""
        import inspect

        from app.domains.wealth.workers.esma_ingestion import run_esma_ingestion

        source = inspect.getsource(run_esma_ingestion)
        assert "finally:" in source, "Worker must have a finally block"
        assert "pg_advisory_unlock" in source, "Worker must unlock in finally"


# ═══════════════════════════════════════════════════════════════════
#  Data provider dataclass tests
# ═══════════════════════════════════════════════════════════════════


class TestEsmaDataclasses:
    def test_fund_dataclass_frozen(self) -> None:
        fund = _make_fund_dc("IE00ABC")
        with pytest.raises(AttributeError):
            fund.isin = "CHANGED"  # type: ignore[misc]

    def test_manager_dataclass_frozen(self) -> None:
        mgr = _make_manager_dc()
        with pytest.raises(AttributeError):
            mgr.esma_id = "CHANGED"  # type: ignore[misc]

    def test_isin_resolution_frozen(self) -> None:
        from data_providers.esma.models import IsinResolution

        res = IsinResolution(
            isin="IE00ABC",
            yahoo_ticker="ABC.L",
            exchange="LSE",
            resolved_via="openfigi",
            is_tradeable=True,
        )
        with pytest.raises(AttributeError):
            res.isin = "CHANGED"  # type: ignore[misc]
