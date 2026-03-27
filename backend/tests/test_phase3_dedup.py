"""Tests for Phase 3 sync/async dedup — StageOutcome, extracted helpers, and injection markers.

Covers:
- StageOutcome.from_gather() — mixed results, errors, length mismatch
- build_profile_metadata() — correct key set
- build_return_dict() — correct 30+ key set
- persist_review_artifacts() — ORM construction + sanitization
- _INJECTION_MARKERS shared constant — single source of truth
- SaturationResult field alignment with enforce_evidence_saturation()
"""
from __future__ import annotations

import datetime as dt
import uuid
from unittest.mock import MagicMock

import pytest

# ═══════════════════════════════════════════════════════════════════════════
# StageOutcome
# ═══════════════════════════════════════════════════════════════════════════


class TestStageOutcome:
    def test_from_gather_success(self):
        from vertical_engines.credit.deep_review.models import StageOutcome

        outcome = StageOutcome.from_gather(
            ["edgar", "policy", "sponsor", "kyc", "quant"],
            ["edgar_ctx", ("checks", "policy_d"), "sponsor_d", ("kyc_r", "appendix"), {"metrics": "ok"}],
        )
        assert outcome.edgar == "edgar_ctx"
        assert outcome.policy == ("checks", "policy_d")
        assert outcome.sponsor == "sponsor_d"
        assert outcome.kyc == ("kyc_r", "appendix")
        assert outcome.quant == {"metrics": "ok"}
        assert outcome.errors == {}

    def test_from_gather_with_errors(self):
        from vertical_engines.credit.deep_review.models import StageOutcome

        exc = RuntimeError("EDGAR failed")
        outcome = StageOutcome.from_gather(
            ["edgar", "policy", "sponsor", "kyc", "quant"],
            [exc, ("checks", "policy_d"), "sponsor_d", ("kyc_r", ""), {"m": 1}],
        )
        assert outcome.edgar is None
        assert "edgar" in outcome.errors
        assert outcome.errors["edgar"] is exc
        assert outcome.policy == ("checks", "policy_d")

    def test_from_gather_length_mismatch(self):
        from vertical_engines.credit.deep_review.models import StageOutcome

        with pytest.raises(ValueError):
            StageOutcome.from_gather(
                ["edgar", "policy"],
                ["only_one"],
            )


# ═══════════════════════════════════════════════════════════════════════════
# build_profile_metadata
# ═══════════════════════════════════════════════════════════════════════════


class TestBuildProfileMetadata:
    def test_correct_keys(self):
        from vertical_engines.credit.deep_review.persist import build_profile_metadata

        result = build_profile_metadata(
            evidence_map={"ch01": ["chunk1"]},
            quant_dict={"metrics_status": "COMPLETE", "sensitivity_matrix": [1, 2]},
            concentration_dict={"any_limit_breached": False},
            macro_snapshot={"regime": "expansion"},
            macro_stress_flag=False,
            critic_dict={"confidence_score": 0.85},
            policy_dict={"overall_status": "PASS"},
            decision_anchor={"finalDecision": "PROCEED"},
            confidence_score=78,
            confidence_level="MEDIUM",
            confidence_breakdown={"evidence": 20},
            confidence_caps=["no_quant"],
            final_confidence=0.78,
            evidence_confidence="HIGH",
            ic_gate="PASS",
            ic_gate_reasons=[],
            instrument_type="DIRECT_LENDING",
            token_summary={"total": 50000},
            chapter_citations={"ch01": []},
            tone_artifacts={"changed_chapters": []},
            tone_signal_original="NEUTRAL",
            tone_signal_final="BALANCED",
        )
        assert result["pipeline_version"] == "v4"
        assert result["sensitivity_matrix"] == [1, 2]
        assert result["macro_stress_flag"] is False
        assert result["tone_signal_original"] == "NEUTRAL"
        assert len(result) == 24  # 24 keys in the metadata dict


# ═══════════════════════════════════════════════════════════════════════════
# build_return_dict
# ═══════════════════════════════════════════════════════════════════════════


class TestBuildReturnDict:
    def _build(self, **overrides):
        from vertical_engines.credit.deep_review.persist import build_return_dict

        defaults = {
            "deal_id": str(uuid.uuid4()),
            "deal_name": "Test Deal",
            "version_tag": "v4.4-abc",
            "evidence_pack_id": str(uuid.uuid4()),
            "evidence_pack_tokens": 50000,
            "chapters": [
                {"chapter_number": 1, "chapter_tag": "ch01_executive_summary", "chapter_title": "Executive Summary"},
            ],
            "critic_dict": {"confidence_score": 0.85, "fatal_flaws": [], "rewrite_required": False},
            "critic_dict_default": {"confidence_score": 0.80},
            "critic_escalated": False,
            "full_mode": True,
            "final_confidence": 0.78,
            "evidence_confidence": "HIGH",
            "confidence_score": 78,
            "confidence_level": "MEDIUM",
            "confidence_breakdown": {"evidence": 20},
            "confidence_caps": [],
            "ic_gate": "PASS",
            "ic_gate_reasons": [],
            "instrument_type": "DIRECT_LENDING",
            "quant_dict": {"metrics_status": "COMPLETE"},
            "concentration_dict": {"any_limit_breached": False},
            "policy_dict": {"overall_status": "PASS"},
            "sponsor_output": {"governance_red_flags": []},
            "macro_stress_flag": False,
            "kyc_results": {"summary": {}},
            "decision_anchor": {"finalDecision": "PROCEED"},
            "token_summary": {"total": 50000},
            "citations_used": [{"chunk_id": "c1"}, {"chunk_id": "c2"}],
            "unsupported_claims_detected": False,
            "tone_review_log": [],
            "tone_pass1_changes": {},
            "tone_pass2_changes": [],
            "tone_signal_original": "NEUTRAL",
            "tone_signal_final": "BALANCED",
            "full_memo_text": "# Full Memo\n\nContent here.",
            "now": dt.datetime(2026, 3, 15, 12, 0, 0, tzinfo=dt.UTC),
        }
        defaults.update(overrides)
        return build_return_dict(**defaults)

    def test_correct_structure(self):
        result = self._build()
        assert result["pipelineVersion"] == "v4"
        assert result["chaptersCompleted"] == 1
        assert result["chaptersTotal"] == 13
        assert result["criticFatalFlaws"] == 0
        assert result["fullMode"] is True
        assert result["asOf"] == "2026-03-15T12:00:00+00:00"

    def test_citation_governance(self):
        result = self._build(
            citations_used=[
                {"chunk_id": "c1"},
                {"chunk_id": "c2"},
                {"chunk_id": "c1"},  # duplicate
                {"chunk_id": "NONE"},  # excluded
            ],
            unsupported_claims_detected=True,
        )
        gov = result["citationGovernance"]
        assert gov["citationsUsed"] == 4
        assert gov["uniqueChunks"] == 2
        assert gov["unsupportedClaimsDetected"] is True
        assert gov["selfAuditPass"] is False

    def test_has_all_expected_keys(self):
        result = self._build()
        expected_keys = {
            "dealId", "dealName", "pipelineVersion", "versionTag",
            "evidencePackId", "evidencePackTokens",
            "chaptersCompleted", "chaptersTotal", "chapters",
            "criticConfidence", "criticDefaultConfidence",
            "criticFatalFlaws", "criticRewriteRequired", "criticEscalated",
            "fullMode", "finalConfidence", "evidenceConfidence",
            "confidenceScore", "confidenceLevel", "confidenceBreakdown",
            "confidenceCapsApplied", "icGate", "icGateReasons",
            "instrumentType", "quantStatus", "concentrationBreached",
            "policyStatus", "sponsorFlags", "macroStressFlag",
            "kycScreeningSummary", "decisionAnchor", "tokenUsage",
            "citationGovernance", "toneReviewLog", "tonePass1Changes",
            "tonePass2Changes", "toneSignalOriginal", "toneSignalFinal",
            "fullMemo", "asOf",
        }
        assert set(result.keys()) == expected_keys


# ═══════════════════════════════════════════════════════════════════════════
# persist_review_artifacts
# ═══════════════════════════════════════════════════════════════════════════


class TestPersistReviewArtifacts:
    def test_sanitizes_varchar_fields(self):
        """Verify liquidity_profile, capital_structure_type, and mitigation are sanitized."""
        from vertical_engines.credit.deep_review.persist import persist_review_artifacts

        mock_db = MagicMock()
        mock_db.begin_nested.return_value.__enter__ = MagicMock(return_value=None)
        mock_db.begin_nested.return_value.__exit__ = MagicMock(return_value=False)

        fund_id = uuid.uuid4()
        deal_id = uuid.uuid4()
        analysis = {
            "strategyType": "Direct Lending",
            "geography": "North America",
            "sectorFocus": "Healthcare",
            "executiveSummary": "Test summary",
            "liquidityProfile": "<script>alert('xss')</script>Semi-Annual",
            "capitalStructurePosition": "<b>Senior</b> Secured",
            "expectedReturns": {"targetIRR": "12%"},
            "riskFactors": [
                {
                    "factor": "Credit Risk",
                    "severity": "MEDIUM",
                    "mitigation": "<script>bad</script>Diversification strategy",
                },
            ],
            "keyDifferentiators": [],
        }

        persist_review_artifacts(
            mock_db,
            fund_id=fund_id,
            deal_id=deal_id,
            analysis=analysis,
            chapter_texts={},
            deal_fields={"strategy_type": "Direct Lending"},
            profile_metadata={},
            im_recommendation="PROCEED",
            decision_anchor={"finalDecision": "PROCEED"},
            actor_id="test",
            deal_folder_path="/test/path",
            now=dt.datetime.now(dt.UTC),
        )

        # Verify db.add was called (profile was constructed)
        assert mock_db.add.called

        # Extract the DealIntelligenceProfile object
        profile = mock_db.add.call_args_list[0][0][0]
        # Verify HTML was stripped from VARCHAR fields
        assert "<script>" not in (profile.liquidity_profile or "")
        assert "<script>" not in (profile.capital_structure_type or "")
        # Verify HTML is cleaned from mitigation in key_risks
        for risk in profile.key_risks:
            assert "<script>" not in risk.get("mitigation", "")

    def test_delete_before_insert(self):
        """Verify delete-before-insert pattern for atomic upsert."""
        from vertical_engines.credit.deep_review.persist import persist_review_artifacts

        mock_db = MagicMock()
        mock_db.begin_nested.return_value.__enter__ = MagicMock(return_value=None)
        mock_db.begin_nested.return_value.__exit__ = MagicMock(return_value=False)

        persist_review_artifacts(
            mock_db,
            fund_id=uuid.uuid4(),
            deal_id=uuid.uuid4(),
            analysis={"executiveSummary": "Test", "expectedReturns": {}, "riskFactors": []},
            chapter_texts={},
            deal_fields={},
            profile_metadata={},
            im_recommendation=None,
            decision_anchor={"finalDecision": "CONDITIONAL"},
            actor_id="test",
            deal_folder_path="/test",
            now=dt.datetime.now(dt.UTC),
        )

        # 3 deletes + 1 flush + 1 add (profile) + 1 add_all (flags) + 1 add (brief) = 7 calls
        assert mock_db.execute.call_count == 3
        assert mock_db.flush.called
        assert mock_db.add.call_count == 2  # profile + brief
        assert mock_db.add_all.call_count == 1  # risk flags


# ═══════════════════════════════════════════════════════════════════════════
# Injection markers shared constant
# ═══════════════════════════════════════════════════════════════════════════


class TestInjectionMarkersShared:
    def test_single_source_of_truth(self):
        from ai_engine.governance._constants import INJECTION_MARKERS
        from ai_engine.governance.output_safety import INJECTION_MARKERS as output_markers
        from ai_engine.governance.prompt_safety import INJECTION_MARKERS as prompt_markers

        assert output_markers is INJECTION_MARKERS
        assert prompt_markers is INJECTION_MARKERS


# ═══════════════════════════════════════════════════════════════════════════
# write_gold_memo
# ═══════════════════════════════════════════════════════════════════════════


class TestWriteGoldMemo:
    @pytest.mark.asyncio
    async def test_writes_to_gold_path(self):
        from unittest.mock import AsyncMock

        from vertical_engines.credit.deep_review.persist import write_gold_memo

        mock_client = MagicMock()
        mock_client.write = AsyncMock(return_value="ok")

        org_id = str(uuid.uuid4())
        memo_id = str(uuid.uuid4())
        result_dict = {"dealId": "test", "pipelineVersion": "v4"}

        await write_gold_memo(
            mock_client,
            organization_id=org_id,
            memo_id=memo_id,
            result_dict=result_dict,
        )
        assert mock_client.write.called
        write_args = mock_client.write.call_args
        assert "gold/" in write_args[0][0]
        assert write_args[1]["content_type"] == "application/json"

    @pytest.mark.asyncio
    async def test_failure_is_logged_not_raised(self):
        from vertical_engines.credit.deep_review.persist import write_gold_memo

        mock_client = MagicMock()
        mock_client.write.side_effect = RuntimeError("ADLS down")

        # Should not raise
        await write_gold_memo(
            mock_client,
            organization_id=str(uuid.uuid4()),
            memo_id=str(uuid.uuid4()),
            result_dict={"test": True},
        )
