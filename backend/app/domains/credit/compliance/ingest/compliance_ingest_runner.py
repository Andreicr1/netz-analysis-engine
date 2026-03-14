"""Unified Compliance Knowledge Base ingestion engine.
Consolidates: Fund Constitution · Service Providers · CIMA Regulation
into compliance-global-index (JSON stores under backend/data/compliance/).

Paths are resolved relative to this file so the runner works regardless
of the CWD (from workspace root or from backend/).
"""
from __future__ import annotations

import json
from pathlib import Path

from app.domains.credit.compliance.ingest.compliance_kb_schema import (
    ComplianceChunk,
    ComplianceDocument,
)
from app.domains.credit.compliance.ingest.obligation_candidate import detect_obligation_candidate

# Resolved relative to this file: backend/app/domain/compliance/ingest/ → 4 parents up = backend/
_BACKEND_ROOT = Path(__file__).parents[4]
KB_DOC_STORE = _BACKEND_ROOT / "data" / "compliance" / "kb_documents.json"
KB_CHUNK_STORE = _BACKEND_ROOT / "data" / "compliance" / "kb_chunks.json"


# ── I/O helpers ───────────────────────────────────────────────────────────────


def _ensure_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _save_json(path: Path, payload: dict) -> None:
    _ensure_dir(path)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


# ── Chunker ───────────────────────────────────────────────────────────────────


def chunk_text(text: str, max_chars: int = 1200) -> list[str]:
    """Deterministic paragraph-boundary chunker (no LLM).
    Splits on blank lines first; groups short paragraphs together
    until the buffer reaches max_chars.
    """
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""

    for para in paras:
        if len(current) + len(para) < max_chars:
            current = (current + "\n\n" + para).strip()
        else:
            if current:
                chunks.append(current)
            current = para

    if current.strip():
        chunks.append(current.strip())

    return chunks or [text.strip()]


# ── Runner ────────────────────────────────────────────────────────────────────


class ComplianceIngestRunner:
    """Unified Compliance Knowledge Base ingestion engine.

    Usage::

        runner = ComplianceIngestRunner()
        runner.ingest_document(...)
        result = runner.persist()

    Or use the ``run()`` shortcut for the full pipeline::

        runner = ComplianceIngestRunner()
        result = runner.run(fund_id="...")
    """

    # Known compliance document catalog — extracted from the seed script.
    # Each entry maps directly to ingest_document() kwargs.
    _DEFAULT_SOURCES: list[dict] = [
        {
            "doc_id": "DOC-CIMA-001",
            "title": "CIMA Regulatory Handbook",
            "domain": "REGULATORY",
            "doc_type": "CIMA_HANDBOOK",
            "source_blob": "regulatory-library-cima/RegulatoryHandbookVolume1_1751062003.pdf",
            "raw_text": (
                "Funds must file an annual return with CIMA by the prescribed deadline.\n"
                "Audited financial statements shall be submitted annually to the regulator.\n\n"
                "The licensee is required to file all regulatory filings in accordance with the SIBL.\n"
                "Failure to submit to CIMA within the prescribed period may result in penalties.\n\n"
                "Funds shall notify CIMA of any material change in the fund's structure."
            ),
            "provider": "CIMA",
        },
        {
            "doc_id": "DOC-CIMA-002",
            "title": "Anti-Money Laundering Regulations 2025 Revision",
            "domain": "REGULATORY",
            "doc_type": "CIMA_REGULATION",
            "source_blob": (
                "regulatory-library-cima/"
                "Anti-MoneyLaunderingRegulations2025Revision_LG6_S1_1738770781.pdf"
            ),
            "raw_text": (
                "The AML reporting officer shall conduct an annual review of the AML program.\n"
                "AML reporting must be submitted to CIMA as prescribed.\n\n"
                "Regulated entities are required to file periodic reports confirming\n"
                "compliance status of their anti-money laundering procedures.\n\n"
                "Review annually all policies and procedures to ensure they remain current\n"
                "and effective. Any material deficiency must be notified to the regulator."
            ),
            "provider": "CIMA",
        },
        {
            "doc_id": "DOC-CIMA-003",
            "title": "Cayman Directors Registration and Licensing Act",
            "domain": "REGULATORY",
            "doc_type": "CIMA_REGULATION",
            "source_blob": (
                "fund-constitution-governance/"
                "9.1 (Cayman) The Directors Registration and Licensing Act.pdf"
            ),
            "raw_text": (
                "Every director must file a registration with CIMA.\n"
                "Licensed under this Act, directors shall renew their registration annually.\n\n"
                "The annual return must be filed with the Registrar on or before the prescribed date.\n"
                "Failure to renew or notify within the deadline may result in suspension of licence."
            ),
            "provider": "CIMA",
        },
        {
            "doc_id": "DOC-IMA-001",
            "title": "Investment Management Agreement — Netz Private Credit Fund",
            "domain": "CONSTITUTION",
            "doc_type": "IMA",
            "source_blob": "fund-constitution-governance/IMA - Netz Private Credit Fund - FINAL.pdf",
            "raw_text": (
                "The Investment Manager shall provide quarterly reporting to the Board of Directors.\n"
                "The fund shall maintain an annual audit cycle in accordance with the Fund Documents.\n\n"
                "Audited financial statements shall be prepared and distributed to investors\n"
                "within 180 days of the fiscal year end. The Manager shall submit to CIMA\n"
                "a copy of the audited accounts within the regulatory prescribed period.\n\n"
                "The Manager shall notify the Board of any material matter within 30 days."
            ),
            "provider": "Netz Capital",
        },
        {
            "doc_id": "DOC-ZEDRA-001",
            "title": "Zedra Fund Administration Engagement Letter",
            "domain": "SERVICE_PROVIDER",
            "doc_type": "ENGAGEMENT_LETTER",
            "source_blob": "service-providers-contracts/(Zedra) Engagement Letter.pdf",
            "raw_text": (
                "This engagement is subject to annual renewal notice by either party.\n"
                "The Administrator shall notify the fund of any material breach within 10 business days.\n\n"
                "Service fees shall be reviewed annually in accordance with Schedule A.\n"
                "The fund is required to provide to the Administrator, within 5 business days,\n"
                "all necessary data to prepare the quarterly NAV and investor reporting."
            ),
            "provider": "Zedra",
        },
    ]

    def __init__(self) -> None:
        self.documents: list[ComplianceDocument] = []
        self.chunks: list[ComplianceChunk] = []

    def run(self, fund_id: str | None = None) -> dict:
        """Run the full compliance ingest pipeline.

        Processes all known compliance document sources and persists the KB.
        ``fund_id`` is accepted for dispatch compatibility but currently all
        compliance documents are global (not fund-scoped).
        """
        import logging as _logging

        _log = _logging.getLogger(__name__)
        _log.info("ComplianceIngestRunner.run started fund_id=%s", fund_id)

        for src in self._DEFAULT_SOURCES:
            self.ingest_document(**src)

        result = self.persist()
        _log.info("ComplianceIngestRunner.run completed result=%s", result)
        return result

    def ingest_document(
        self,
        doc_id: str,
        title: str,
        domain: str,
        doc_type: str,
        source_blob: str,
        raw_text: str,
        provider: str | None = None,
        effective_date: str | None = None,
    ) -> None:
        doc = ComplianceDocument(
            doc_id=doc_id,
            title=title,
            domain=domain,           # type: ignore[arg-type]
            doc_type=doc_type,       # type: ignore[arg-type]
            provider=provider,
            source_blob=source_blob,
            effective_date=effective_date,
        )
        self.documents.append(doc)

        for i, block in enumerate(chunk_text(raw_text)):
            detection = detect_obligation_candidate(block)
            chunk = ComplianceChunk(
                chunk_id=f"{doc_id}-CH{i + 1:03d}",
                doc_id=doc_id,
                domain=domain,           # type: ignore[arg-type]
                doc_type=doc_type,       # type: ignore[arg-type]
                source_blob=source_blob,
                chunk_text=block,
                obligation_candidate=detection["is_candidate"],
                extraction_confidence=detection["confidence"],
                source_snippet=block[:300],
            )
            self.chunks.append(chunk)

    def persist(self) -> dict:
        _save_json(
            KB_DOC_STORE,
            {"documents": [d.model_dump() for d in self.documents]},
        )
        _save_json(
            KB_CHUNK_STORE,
            {"chunks": [c.model_dump() for c in self.chunks]},
        )
        candidates = sum(1 for c in self.chunks if c.obligation_candidate)
        return {
            "documents": len(self.documents),
            "chunks": len(self.chunks),
            "obligation_candidates": candidates,
        }
