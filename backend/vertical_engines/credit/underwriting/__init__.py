"""Underwriting Artifact — single IC truth source for deal underwriting.

Public API:
    persist_underwriting_artifact()  — create artifact, deactivate priors
    get_active_artifact()            — query active artifact for a deal
    get_artifact_history()           — query all versions for a deal
    derive_risk_band()               — deterministic risk band from analysis
    confidence_to_level()            — map 0.0-1.0 score to HIGH/MEDIUM/LOW
    compute_evidence_pack_hash()     — stable SHA-256 of evidence pack

Error contract: raises-on-failure (pure deterministic + transactional).
Standard exceptions for truly exceptional cases.
"""
from vertical_engines.credit.underwriting.derivation import (
    compute_evidence_pack_hash,
    confidence_to_level,
    derive_risk_band,
)
from vertical_engines.credit.underwriting.persistence import (
    get_active_artifact,
    get_artifact_history,
    persist_underwriting_artifact,
)

__all__ = [
    "persist_underwriting_artifact",
    "get_active_artifact",
    "get_artifact_history",
    "derive_risk_band",
    "confidence_to_level",
    "compute_evidence_pack_hash",
]
