"""Phase 7 — analysis_peer queries + routes.

Full assertions require seeded production data (mv_unified_funds rows with
fund_risk_metrics, sec_nport_holdings, sec_13f_holdings for curated institutions
with cik backfilled). The test bodies below serve as contract documentation for
when those fixtures become available.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(
    reason="requires seeded prod data + dev_headers/sample_fund_id fixtures",
)


def test_peer_comparison_includes_subject(client, dev_headers, sample_fund_id):
    r = client.get(
        f"/wealth/discovery/funds/{sample_fund_id}/analysis/peers?limit=20",
        headers=dev_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert "peers" in body
    assert body["subject"] is not None
    assert any(p["is_subject"] for p in body["peers"])
    assert all("sharpe_1y" in p for p in body["peers"])


def test_peer_comparison_limits(client, dev_headers, sample_fund_id):
    r = client.get(
        f"/wealth/discovery/funds/{sample_fund_id}/analysis/peers?limit=5",
        headers=dev_headers,
    )
    assert r.status_code == 200
    assert len(r.json()["peers"]) <= 5


def test_institutional_reveal_shape(client, dev_headers, sample_fund_id):
    r = client.get(
        f"/wealth/discovery/funds/{sample_fund_id}/analysis/institutional-reveal",
        headers=dev_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert "institutions" in body
    assert "overlap_matrix" in body
    assert "holdings" in body


def test_institutional_reveal_category_filter(client, dev_headers, sample_fund_id):
    r = client.get(
        f"/wealth/discovery/funds/{sample_fund_id}/analysis/institutional-reveal"
        "?categories=endowment,family_office",
        headers=dev_headers,
    )
    assert r.status_code == 200
    body = r.json()
    for inst in body["institutions"]:
        assert inst["category"] in {"endowment", "family_office"}
