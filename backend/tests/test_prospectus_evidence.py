"""Unit tests for prospectus data gathering in DD Report evidence pack."""

from unittest.mock import MagicMock


def test_gather_prospectus_stats_no_cik():
    """Returns empty dict when fund_cik and series_id both None."""
    from vertical_engines.wealth.dd_report.sec_injection import gather_prospectus_stats

    db = MagicMock()
    result = gather_prospectus_stats(db, fund_cik=None)
    assert result == {}
    db.query.assert_not_called()


def test_gather_prospectus_returns_no_cik():
    """Returns empty list when fund_cik and series_id both None."""
    from vertical_engines.wealth.dd_report.sec_injection import gather_prospectus_returns

    db = MagicMock()
    result = gather_prospectus_returns(db, fund_cik=None)
    assert result == []
    db.query.assert_not_called()


def test_resolve_series_id_no_cik():
    """Returns None when cik is None."""
    from vertical_engines.wealth.dd_report.sec_injection import _resolve_series_id

    db = MagicMock()
    result = _resolve_series_id(db, None)
    assert result is None
    db.query.assert_not_called()


def test_build_evidence_pack_with_prospectus():
    """EvidencePack accepts and exposes prospectus fields."""
    from vertical_engines.wealth.dd_report.evidence_pack import build_evidence_pack

    pack = build_evidence_pack(
        fund_data={"instrument_id": "test-id", "name": "Test Fund"},
        prospectus_stats={"prospectus_stats_available": True, "expense_ratio_pct": 0.03},
        prospectus_returns=[{"year": 2024, "annual_return_pct": 24.8}],
    )

    assert pack.prospectus_stats["prospectus_stats_available"] is True
    assert pack.prospectus_stats["expense_ratio_pct"] == 0.03
    assert len(pack.prospectus_returns) == 1
    assert pack.prospectus_returns[0]["year"] == 2024

    ctx = pack.to_context()
    assert ctx["prospectus_data_available"] is True
    assert ctx["prospectus_returns"][0]["annual_return_pct"] == 24.8


def test_evidence_pack_empty_prospectus():
    """prospectus_data_available is False when prospectus_stats is empty."""
    from vertical_engines.wealth.dd_report.evidence_pack import build_evidence_pack

    pack = build_evidence_pack(
        fund_data={"instrument_id": "test-id", "name": "Test Fund"},
    )

    ctx = pack.to_context()
    assert ctx["prospectus_data_available"] is False
    assert ctx["prospectus_returns"] == []
