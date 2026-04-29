"""C-14: strategy_reclassification _read_esma_funds must use lei, not isin.

Tests that:
- The SQL in _read_esma_funds references esma_funds.lei (post-Q11B PK),
  not the pre-Q11B isin column.
- The reader yields _FundRow with source_pk from the lei column.
"""

from __future__ import annotations

import inspect

import pytest

from app.domains.wealth.workers.strategy_reclassification import (
    _read_esma_funds,
)


class TestEsmaFundsLeiReference:
    """Verify _read_esma_funds references lei after Q11B migration."""

    def test_sql_uses_lei_not_isin(self):
        """The SQL text in _read_esma_funds must SELECT lei, not isin."""
        source = inspect.getsource(_read_esma_funds)

        # Must reference lei
        assert "lei" in source, (
            "_read_esma_funds must SELECT lei (post-Q11B PK)"
        )

        # Must NOT reference isin as a column (the old broken reference)
        # We check for the specific SQL pattern "isin AS pk" or "ORDER BY isin"
        assert "isin" not in source.lower(), (
            "_read_esma_funds must not reference isin — "
            "Q11B renamed it to legacy_isin_misnamed and changed PK to lei"
        )

    def test_reader_in_dispatch_table(self):
        """_read_esma_funds must be wired in the source dispatch table."""
        from app.domains.wealth.workers.strategy_reclassification import (
            _reader_for_source,
        )

        reader = _reader_for_source("esma_funds")
        assert reader is _read_esma_funds

    @pytest.mark.asyncio
    async def test_reader_yields_fund_row_with_lei_pk(self):
        """When given a mock DB that returns a row, the reader must
        populate source_pk from the 'pk' column (which is lei)."""
        from unittest.mock import AsyncMock, MagicMock

        mock_db = AsyncMock()
        # Simulate a single row returned by the SQL query
        mock_mapping = {
            "pk": "529900ABC123DEF456GH",  # LEI format (20 chars)
            "fund_name": "Test UCITS Fund",
            "fund_type": "UCITS",
            "current_label": "Long/Short Equity",
        }
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = [mock_mapping]
        mock_db.execute.return_value = mock_result

        rows = []
        async for row in _read_esma_funds(mock_db, limit=5):
            rows.append(row)

        assert len(rows) == 1
        assert rows[0].source_table == "esma_funds"
        assert rows[0].source_pk == "529900ABC123DEF456GH"
        assert rows[0].fund_name == "Test UCITS Fund"
        assert rows[0].fund_type == "UCITS"
        assert rows[0].current_strategy_label == "Long/Short Equity"
        assert rows[0].tiingo_description is None

        # Verify the SQL sent to DB references lei
        sql_arg = str(mock_db.execute.call_args[0][0])
        assert "lei" in sql_arg.lower()
        assert "isin" not in sql_arg.lower()
