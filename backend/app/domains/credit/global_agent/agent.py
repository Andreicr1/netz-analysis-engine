"""Netz Global Intelligence Agent.

Single unified agent that answers questions across all knowledge sources:
  - Investment Pipeline (deal documents, deal_context.json)
  - Fund Constitution (LPA, IMA, subscription docs)
  - Regulatory (CIMA regulations, handbooks)
  - Service Providers (administrator, auditor, legal counsel contracts)

The agent performs parallel retrieval across relevant indexes,
merges evidence, and generates a grounded answer with citations.
Never speculates. Answers only from evidence.
"""
from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from sqlalchemy.orm import Session

from ai_engine.prompts import prompt_registry
from ai_engine.validation.citation_formatter import format_citations
from ai_engine.validation.evidence_quality import (
    compute_confidence,
    cross_validate_answer,
    recency_analysis,
)
from app.domains.credit.ai.services.agent_context import AgentUIContext, build_agent_runtime_context
from app.domains.credit.global_agent.intent_router import IntentRouter

logger = logging.getLogger(__name__)

# Compliance domains served by AzureComplianceKBAdapter
_COMPLIANCE_DOMAINS = {"REGULATORY", "CONSTITUTION", "SERVICE_PROVIDER"}

PIPELINE_CONTAINER = "investment-pipeline-intelligence"


class NetzGlobalAgent:
    """Stateless agent: each call resolves its own search clients + LLM.
    Safe for concurrent use — no shared mutable state.
    """

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #
    def answer(
        self,
        question: str,
        fund_id: uuid.UUID | None = None,
        deal_folder: str | None = None,
        domains: list[str] | None = None,
        top: int = 10,
        db: Session | None = None,
        actor: Any | None = None,
        organization_id: uuid.UUID | str | None = None,
        ui_context: dict[str, Any] | None = None,
        system_prompt_override: str | None = None,
    ) -> dict[str, Any]:
        """End-to-end: detect intent → parallel retrieve → RBAC filter →
        merge → deal-context inject → LLM → quality → return.

        Parameters
        ----------
        question : str
            Natural-language question across any knowledge domain.
        deal_folder : str | None
            Deal slug to scope pipeline retrieval.
        domains : list[str] | None
            Force specific domains. None = auto-detect via IntentRouter.
        top : int
            Max chunks to feed to the LLM.
        actor : Actor | None
            If provided, scope-filter chunks via RBAC. None = skip filtering
            (for internal AI engine calls).

        Returns
        -------
        dict matching GlobalAgentResponse schema.

        """
        # 1. Intent routing
        if domains:
            resolved_domains = list(domains)
        else:
            resolved_domains = IntentRouter.detect_domains(question, deal_folder)

        logger.info(
            "GLOBAL_AGENT question=%r domains=%s deal_folder=%s",
            question[:80],
            resolved_domains,
            deal_folder,
        )

        # 2. Parallel retrieval — use higher top for broad pipeline queries
        effective_top = top
        if not deal_folder and "PIPELINE" in resolved_domains:
            # For global pipeline queries, fetch more chunks to ensure deal diversity
            effective_top = max(top, 30)

        # Resolve org_id: explicit parameter > actor.org_id > None
        org_id = organization_id or (getattr(actor, "org_id", None) if actor else None)

        all_chunks = self._parallel_retrieve(
            question, resolved_domains, deal_folder, effective_top, org_id,
        )

        # 3. RBAC filter
        if actor is not None:
            all_chunks = self._apply_rbac(actor, all_chunks)

        # 4. Evidence merge — deduplicate, sort, cap
        all_chunks = self._merge_chunks(all_chunks, top)

        # 5. Deal context injection
        if deal_folder:
            deal_ctx_chunk = self._load_deal_context_chunk(deal_folder)
            if deal_ctx_chunk is not None:
                # Prepend as first chunk (highest priority per source hierarchy)
                all_chunks = [deal_ctx_chunk] + all_chunks

        if not all_chunks:
            logger.warning(
                "GLOBAL_AGENT NO_CHUNKS question=%r", question[:80],
            )
            return {
                "answer": "Insufficient evidence in indexed documents.",
                "citations": [],
                "chunks_used": 0,
                "domains_queried": resolved_domains,
                "deal_folder": deal_folder,
                "retrieval_confidence": 0.0,
                "confidence_components": {},
                "cross_validation": {
                    "has_critical_claims": False,
                    "claims": [],
                    "overall_status": "NO_CRITICAL_CLAIMS",
                },
                "recency": {
                    "revisions_detected": [],
                    "most_recent": None,
                    "mixed_revisions": False,
                    "outdated_chunks": [],
                    "recency_warning": None,
                    "last_modified_range": {"earliest": None, "latest": None},
                },
            }

        # 6. LLM call
        source_blobs = {
            getattr(c, "source_blob", "") for c in all_chunks
            if getattr(c, "source_blob", "") and getattr(c, "source_blob", "") != "unknown"
        }
        user_prompt = prompt_registry.render(
            "services/copilot_user.j2",
            question=question,
            chunk_count=len(all_chunks),
            source_count=len(source_blobs),
            chunks=self._serialize_chunks(all_chunks),
            runtime_context=build_agent_runtime_context(
                actor=actor,
                db=db,
                fund_id=fund_id,
                deal_folder=deal_folder,
                domains=resolved_domains,
                ui_context=AgentUIContext(
                    current_view=(ui_context or {}).get("current_view"),
                    entity_type=(ui_context or {}).get("entity_type"),
                    entity_id=(ui_context or {}).get("entity_id"),
                    entity_name=(ui_context or {}).get("entity_name"),
                    context_doc_title=(ui_context or {}).get("context_doc_title"),
                ),
            ),
        )
        answer_text = self._call_llm(user_prompt, system_prompt_override=system_prompt_override)

        # 7. Quality analysis
        citations = format_citations(all_chunks)
        confidence = compute_confidence(all_chunks, domain_filter=None)
        cross_validation = cross_validate_answer(answer_text, all_chunks)
        recency = recency_analysis(all_chunks)

        logger.info(
            "GLOBAL_AGENT question=%r domains=%s deal_folder=%s chunks_used=%d",
            question[:80],
            resolved_domains,
            deal_folder,
            len(all_chunks),
        )

        return {
            "answer": answer_text,
            "citations": citations,
            "chunks_used": len(all_chunks),
            "domains_queried": resolved_domains,
            "deal_folder": deal_folder,
            "retrieval_confidence": confidence["retrieval_confidence"],
            "confidence_components": confidence["components"],
            "cross_validation": cross_validation,
            "recency": recency,
        }

    # ------------------------------------------------------------------ #
    # Parallel Retrieval                                                  #
    # ------------------------------------------------------------------ #
    def _parallel_retrieve(
        self,
        question: str,
        domains: list[str],
        deal_folder: str | None,
        top: int,
        organization_id: uuid.UUID | str | None = None,
    ) -> list[Any]:
        """Fan out to relevant adapters concurrently using ThreadPoolExecutor.
        """
        futures: dict[Any, str] = {}
        all_chunks: list[Any] = []

        with ThreadPoolExecutor(max_workers=4) as executor:
            # Pipeline retrieval
            if "PIPELINE" in domains:
                fut = executor.submit(
                    self._retrieve_pipeline, question, deal_folder, top, organization_id,
                )
                futures[fut] = "PIPELINE"

            # Compliance domain retrieval (one call per domain)
            compliance_domains = [d for d in domains if d in _COMPLIANCE_DOMAINS]
            for d in compliance_domains:
                fut = executor.submit(
                    self._retrieve_compliance, question, d, top, organization_id,
                )
                futures[fut] = d

            for fut in as_completed(futures):
                domain_label = futures[fut]
                try:
                    chunks = fut.result()
                    all_chunks.extend(chunks)
                except Exception as exc:
                    logger.warning(
                        "GLOBAL_AGENT retrieval failed for %s: %s",
                        domain_label,
                        exc,
                    )

        return all_chunks

    def _retrieve_pipeline(
        self, question: str, deal_folder: str | None, top: int,
        organization_id: uuid.UUID | str | None = None,
    ) -> list[Any]:
        """Retrieve from the canonical env-scoped chunks index."""
        from app.domains.credit.global_agent.pipeline_kb_adapter import PipelineKBAdapter

        if organization_id is None:
            logger.warning("GLOBAL_AGENT pipeline retrieval without organization_id — tenant isolation disabled")
            return []

        try:
            return PipelineKBAdapter.search_live(
                query=question, organization_id=organization_id, deal_folder=deal_folder, top=top,
            )
        except Exception as exc:
            logger.error("GLOBAL_AGENT PIPELINE_RETRIEVAL_ERROR: %s", exc)
            return []

    def _retrieve_compliance(
        self, question: str, domain: str, top: int,
        organization_id: uuid.UUID | str | None = None,
    ) -> list[Any]:
        """Retrieve from dedicated compliance indexes via AzureComplianceKBAdapter."""
        from ai_engine.extraction.azure_kb_adapter import (
            AzureComplianceKBAdapter,
        )

        if organization_id is None:
            logger.warning("GLOBAL_AGENT compliance retrieval without organization_id — tenant isolation disabled")
            return []

        try:
            return AzureComplianceKBAdapter.search_live(
                query=question, domain=domain, organization_id=organization_id, top=top,
            )
        except Exception as exc:
            logger.error(
                "GLOBAL_AGENT COMPLIANCE_RETRIEVAL_ERROR domain=%s: %s",
                domain,
                exc,
            )
            return []

    # ------------------------------------------------------------------ #
    # RBAC                                                                #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _apply_rbac(actor: Any, chunks: list[Any]) -> list[Any]:
        """Post-filter chunks via role-based scope."""
        from app.domains.credit.ai.services.ai_scope import filter_hits_by_scope

        return filter_hits_by_scope(
            actor=actor,
            hits=chunks,
            get_root_folder=lambda c: getattr(c, "root_folder", None),
        )

    # ------------------------------------------------------------------ #
    # Evidence Merge                                                      #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _merge_chunks(chunks: list[Any], top: int) -> list[Any]:
        """Deduplicate by chunk_id, sort by search_score desc, cap at *top*."""
        seen: set[str] = set()
        unique: list[Any] = []
        for c in chunks:
            cid = getattr(c, "chunk_id", None) or "UNKNOWN"
            if cid in seen:
                continue
            seen.add(cid)
            unique.append(c)

        unique.sort(
            key=lambda c: getattr(c, "search_score", None) or 0.0,
            reverse=True,
        )
        return unique[:top]

    # ------------------------------------------------------------------ #
    # Deal Context Injection                                              #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _load_deal_context_chunk(deal_folder: str) -> Any | None:
        """Load deal_context.json from blob and wrap as a synthetic
        ComplianceChunk. Returns None if unavailable.
        """
        from ai_engine.extraction.kb_schema import (
            ComplianceChunk,
        )
        from app.services.blob_storage import blob_uri, download_bytes

        try:
            uri = blob_uri(PIPELINE_CONTAINER, f"{deal_folder}/deal_context.json")
            data = download_bytes(blob_uri=uri)
            json_content = data.decode("utf-8")

            return ComplianceChunk(
                chunk_id="deal_context",
                doc_id="deal_context",
                domain="PIPELINE",
                doc_type="OTHER",
                source_blob=f"{deal_folder}/deal_context.json",
                chunk_text=json_content,
                obligation_candidate=False,
                extraction_confidence=1.0,
                search_score=100.0,  # Highest priority
            )
        except Exception as exc:
            logger.debug(
                "GLOBAL_AGENT deal_context unavailable for %s: %s",
                deal_folder,
                exc,
            )
            return None

    # ------------------------------------------------------------------ #
    # LLM                                                                 #
    # ------------------------------------------------------------------ #
    def _call_llm(self, user_prompt: str, system_prompt_override: str | None = None) -> str:
        """Call the centralised OpenAI provider with the global system prompt.
        Uses gpt-4.1 (policy-grade model) for deterministic, structured answers.
        """
        from ai_engine.model_config import get_model
        from ai_engine.openai_client import create_completion

        try:
            system_prompt = system_prompt_override or prompt_registry.render("services/copilot_system.j2")
            result = create_completion(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=get_model("policy"),
                temperature=0.1,
                max_tokens=4096,
            )
            return result.text
        except Exception as exc:
            logger.error("GLOBAL_AGENT LLM_ERROR: %s", exc)
            return (
                "AGENT_ERROR: Unable to generate response. "
                "Please retry or contact the engineering team."
            )

    # ------------------------------------------------------------------ #
    # Helpers                                                             #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _serialize_chunks(chunks: list[Any]) -> str:
        """Format chunks for the LLM context window with human-readable source names."""
        lines = []
        for c in chunks:
            cid = getattr(c, "chunk_id", "UNKNOWN")
            text = getattr(c, "chunk_text", "")
            doc_type = getattr(c, "doc_type", "")
            source_blob = getattr(c, "source_blob", "") or ""
            domain = getattr(c, "domain", "")

            # Extract human-readable document name from blob path
            # e.g., "deals/Garrington/Garrington_Strategy_Profile.pdf" → "Garrington Strategy Profile.pdf"
            source_name = source_blob.rsplit("/", 1)[-1] if "/" in source_blob else source_blob
            source_name = source_name.replace("_", " ").replace("-", " ") if source_name else "unknown"

            lines.append(
                f"[{cid}] (domain={domain}, doc_type={doc_type}, source={source_name})\n{text}",
            )
        return "\n\n---\n\n".join(lines)
