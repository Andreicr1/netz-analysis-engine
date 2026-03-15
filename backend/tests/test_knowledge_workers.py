"""Tests for knowledge aggregator and outcome recorder — privacy, bucketing, storage."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from worker_app.knowledge_aggregator import (
    _ALLOWED_SIGNAL_FIELDS,
    _ltv_bucket,
    _tenor_bucket,
    _vix_bucket,
    compute_anonymous_hash,
    extract_anonymous_signal,
)
from worker_app.outcome_recorder import _irr_bucket, build_outcome_record

# Fixed UUIDs for deterministic hash tests
ORG_ID = UUID("11111111-1111-1111-1111-111111111111")
DEAL_ID = UUID("22222222-2222-2222-2222-222222222222")
MEMO_ID = UUID("33333333-3333-3333-3333-333333333333")


# ── Bucketing tests ──────────────────────────────────────────────────────────


class TestLTVBucket:
    def test_low(self):
        assert _ltv_bucket(0.30) == "0-40%"

    def test_mid(self):
        assert _ltv_bucket(0.55) == "40-60%"

    def test_high(self):
        assert _ltv_bucket(0.65) == "60-70%"

    def test_very_high(self):
        assert _ltv_bucket(0.80) == "70%+"

    def test_none(self):
        assert _ltv_bucket(None) == "unknown"

    def test_boundary_40(self):
        assert _ltv_bucket(0.40) == "0-40%"

    def test_boundary_60(self):
        assert _ltv_bucket(0.60) == "40-60%"


class TestTenorBucket:
    def test_short(self):
        assert _tenor_bucket(6) == "0-1y"

    def test_medium(self):
        assert _tenor_bucket(24) == "1-3y"

    def test_long(self):
        assert _tenor_bucket(48) == "3-5y"

    def test_very_long(self):
        assert _tenor_bucket(84) == "5y+"

    def test_none(self):
        assert _tenor_bucket(None) == "unknown"


class TestVIXBucket:
    def test_calm(self):
        assert _vix_bucket(12) == "0-15"

    def test_normal(self):
        assert _vix_bucket(20) == "15-25"

    def test_elevated(self):
        assert _vix_bucket(30) == "25-35"

    def test_extreme(self):
        assert _vix_bucket(40) == "35+"

    def test_none(self):
        assert _vix_bucket(None) == "unknown"


class TestIRRBucket:
    def test_low(self):
        assert _irr_bucket(0.03) == "<5%"

    def test_moderate(self):
        assert _irr_bucket(0.08) == "5-10%"

    def test_good(self):
        assert _irr_bucket(0.12) == "10-15%"

    def test_excellent(self):
        assert _irr_bucket(0.20) == "15%+"

    def test_none(self):
        assert _irr_bucket(None) == "unknown"


# ── Anonymous hash tests ─────────────────────────────────────────────────────


class TestAnonymousHash:
    def test_deterministic(self):
        h1 = compute_anonymous_hash(ORG_ID, DEAL_ID, MEMO_ID)
        h2 = compute_anonymous_hash(ORG_ID, DEAL_ID, MEMO_ID)
        assert h1 == h2

    def test_different_inputs_different_hash(self):
        h1 = compute_anonymous_hash(ORG_ID, DEAL_ID, MEMO_ID)
        h2 = compute_anonymous_hash(uuid4(), DEAL_ID, MEMO_ID)
        assert h1 != h2

    def test_hash_is_64_char_hex(self):
        h = compute_anonymous_hash(ORG_ID, DEAL_ID, MEMO_ID)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


# ── Signal extraction tests ─────────────────────────────────────────────────


class TestExtractAnonymousSignal:
    def test_basic_extraction(self):
        signal = extract_anonymous_signal(
            org_id=ORG_ID,
            deal_id=DEAL_ID,
            memo_id=MEMO_ID,
            profile="private_credit",
            memo_result={
                "recommendation": "INVEST",
                "confidence_score": 0.85,
                "chapters": [
                    {"chapter_tag": "ch01_exec", "quality_score": 0.9},
                    {"chapter_tag": "ch02_macro", "quality_score": 0.8},
                ],
                "risk_flags": [{"flag": "a"}, {"flag": "b"}],
                "critic_result": {"fatal_flaw_count": 0},
                "quant_profile": {"ltv": 0.55, "tenor_months": 36, "structure_type": "senior_secured"},
            },
            macro_snapshot={"regime": "RISK_ON", "vix": 18},
        )

        assert signal["profile"] == "private_credit"
        assert signal["recommendation"] == "INVEST"
        assert signal["confidence_score"] == 0.85
        assert signal["chapter_scores"] == {"ch01_exec": 0.9, "ch02_macro": 0.8}
        assert signal["risk_flags_count"] == 2
        assert signal["critic_fatal_flaws"] == 0
        assert signal["ltv_bucket"] == "40-60%"
        assert signal["tenor_bucket"] == "1-3y"
        assert signal["structure_type"] == "senior_secured"
        assert signal["regime"] == "RISK_ON"
        assert signal["vix_bucket"] == "15-25"
        assert "anonymous_hash" in signal
        assert "timestamp" in signal

    def test_no_identifiable_data(self):
        """CRITICAL: Signal must NEVER contain identifiable fields."""
        signal = extract_anonymous_signal(
            org_id=ORG_ID,
            deal_id=DEAL_ID,
            memo_id=MEMO_ID,
            profile="private_credit",
            memo_result={"recommendation": "DECLINE"},
        )

        forbidden = {
            "organization_id", "org_id", "deal_id", "fund_id",
            "document_name", "company_name", "manager_name",
            "borrower_name", "sponsor_name", "geography", "address",
        }
        for field in forbidden:
            assert field not in signal, f"PRIVACY: forbidden field {field!r} found in signal"

    def test_signal_keys_match_allowlist(self):
        """Signal keys must be a subset of the positive allowlist."""
        signal = extract_anonymous_signal(
            org_id=ORG_ID,
            deal_id=DEAL_ID,
            memo_id=MEMO_ID,
            profile="private_credit",
            memo_result={
                "recommendation": "INVEST",
                "confidence_score": 0.85,
                "chapters": [
                    {"chapter_tag": "ch01_exec", "quality_score": 0.9},
                ],
                "risk_flags": [{"flag": "a"}],
                "critic_result": {"fatal_flaw_count": 1},
                "quant_profile": {"ltv": 0.55, "tenor_months": 36, "structure_type": "senior_secured"},
            },
            macro_snapshot={"regime": "RISK_ON", "vix": 18},
        )
        assert set(signal.keys()) <= _ALLOWED_SIGNAL_FIELDS

    def test_missing_fields_use_defaults(self):
        signal = extract_anonymous_signal(
            org_id=ORG_ID,
            deal_id=DEAL_ID,
            memo_id=MEMO_ID,
            profile="private_credit",
            memo_result={},
        )
        assert signal["recommendation"] == "UNKNOWN"
        assert signal["confidence_score"] is None
        assert signal["ltv_bucket"] == "unknown"
        assert signal["tenor_bucket"] == "unknown"


# ── Outcome recorder tests ───────────────────────────────────────────────────


class TestBuildOutcomeRecord:
    def test_converted_deal(self):
        record = build_outcome_record(
            org_id=ORG_ID,
            deal_id=DEAL_ID,
            memo_id=MEMO_ID,
            converted=True,
            months_to_conversion=4.5,
            irr=0.12,
        )
        assert record["converted"] is True
        assert record["months_to_conversion"] == "3-6"
        assert record["irr_bucket"] == "10-15%"
        assert "anonymous_hash" in record
        assert "timestamp" in record

    def test_not_converted_deal(self):
        record = build_outcome_record(
            org_id=ORG_ID,
            deal_id=DEAL_ID,
            memo_id=MEMO_ID,
            converted=False,
        )
        assert record["converted"] is False
        assert record["months_to_conversion"] == "unknown"
        assert record["irr_bucket"] == "unknown"

    def test_hash_matches_aggregator(self):
        """Outcome hash must match aggregator hash for the same deal."""
        signal_hash = compute_anonymous_hash(ORG_ID, DEAL_ID, MEMO_ID)
        record = build_outcome_record(
            org_id=ORG_ID,
            deal_id=DEAL_ID,
            memo_id=MEMO_ID,
            converted=True,
        )
        assert record["anonymous_hash"] == signal_hash


# ── Storage integration tests ────────────────────────────────────────────────


class TestAggregateStorage:
    @pytest.mark.asyncio
    async def test_aggregate_writes_to_storage(self, tmp_path):
        from unittest.mock import patch

        from app.services.storage_client import LocalStorageClient

        storage = LocalStorageClient(root=tmp_path)
        with patch("app.services.storage_client.get_storage_client", return_value=storage):
            from worker_app.knowledge_aggregator import aggregate_memo_signal

            path = await aggregate_memo_signal(
                org_id=ORG_ID,
                deal_id=DEAL_ID,
                memo_id=MEMO_ID,
                profile="private_credit",
                memo_result={"recommendation": "INVEST", "confidence_score": 0.85},
            )

            assert path.startswith("gold/_global/analysis_patterns/private_credit/")
            assert await storage.exists(path)

            import json

            data = json.loads(await storage.read(path))
            assert data["profile"] == "private_credit"
            assert data["recommendation"] == "INVEST"

    @pytest.mark.asyncio
    async def test_record_outcome_writes_to_storage(self, tmp_path):
        from unittest.mock import patch

        from app.services.storage_client import LocalStorageClient

        storage = LocalStorageClient(root=tmp_path)
        with patch("app.services.storage_client.get_storage_client", return_value=storage):
            from worker_app.outcome_recorder import record_outcome

            path = await record_outcome(
                org_id=ORG_ID,
                deal_id=DEAL_ID,
                memo_id=MEMO_ID,
                converted=True,
                months_to_conversion=2,
                irr=0.08,
            )

            assert path.startswith("gold/_global/analysis_patterns/outcomes/")
            assert await storage.exists(path)

            import json

            data = json.loads(await storage.read(path))
            assert data["converted"] is True
            assert data["irr_bucket"] == "5-10%"
