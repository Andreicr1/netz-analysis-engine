"""Wealth AI Agent — SSE-streamed RAG assistant.

POST /wealth/agent/chat → SSE stream with tool_call / chunk / answer / error events.
Searches wealth_vector_chunks (12 embedding sources) scoped by organization + optional instrument.
Uses fetch() + ReadableStream on frontend (not EventSource — auth headers needed).
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse, ServerSentEvent  # type: ignore[attr-defined]

from app.core.security.clerk_auth import Actor, get_actor
from app.core.tenancy.middleware import get_org_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wealth/agent", tags=["wealth-agent"])


# ── Schemas ──────────────────────────────────────────────────────────────


class ChatMessage(BaseModel):
    role: str = Field(description="'user' or 'assistant'")
    content: str


class AgentChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)
    instrument_id: str | None = Field(default=None, description="Scope to a specific fund")
    sec_crd: str | None = Field(default=None, description="Manager CRD for firm context")
    esma_manager_id: str | None = Field(default=None, description="ESMA manager ID for firm context")


# ── SSE event helpers ────────────────────────────────────────────────────


def _sse(event: str, data: dict[str, Any]) -> ServerSentEvent:  # type: ignore[type-arg]
    return ServerSentEvent(data=json.dumps(data), event=event)


# ── Route ────────────────────────────────────────────────────────────────


@router.post("/chat")
async def agent_chat(
    payload: AgentChatRequest,
    request: Request,
    actor: Actor = Depends(get_actor),
    org_id: uuid.UUID = Depends(get_org_id),
) -> EventSourceResponse:
    """Stream a RAG-grounded answer via SSE.

    Event types:
      tool_call  — {tool, status, detail}  (retrieval/embedding progress)
      chunk      — {text}                  (incremental answer tokens)
      citations  — {citations: [...]}      (source references)
      done       — {}                      (terminal)
      error      — {message}               (terminal)
    """
    if not actor.organization_id:
        raise HTTPException(status_code=403, detail="Organization context required")

    # Extract the latest user message (last in the list)
    user_messages = [m for m in payload.messages if m.role == "user"]
    if not user_messages:
        raise HTTPException(status_code=422, detail="At least one user message required")

    question = user_messages[-1].content

    # Build conversation history for multi-turn context
    history_lines: list[str] = []
    for m in payload.messages[:-1]:  # exclude last (current question)
        history_lines.append(f"{m.role.upper()}: {m.content}")
    history_context = "\n".join(history_lines[-10:]) if history_lines else ""

    async def event_generator() -> AsyncGenerator[ServerSentEvent, None]:
        try:
            # ── Step 1: Embed the question ──
            yield _sse("tool_call", {"tool": "embedding", "status": "running", "detail": "Generating query embedding…"})

            from ai_engine.extraction.embedding_service import generate_embeddings

            try:
                emb = generate_embeddings([question])
                query_vector = emb.vectors[0] if emb.vectors else None
            except Exception:
                query_vector = None

            if not query_vector:
                yield _sse("error", {"message": "Failed to generate query embedding"})
                return

            yield _sse("tool_call", {"tool": "embedding", "status": "complete", "detail": "Query embedded"})

            # ── Step 2: Parallel retrieval from wealth_vector_chunks ──
            yield _sse("tool_call", {"tool": "vector_search", "status": "running", "detail": "Searching knowledge base…"})

            from ai_engine.extraction.pgvector_search_service import (
                search_fund_analysis_sync,
                search_fund_firm_context_sync,
            )

            all_chunks: list[dict[str, Any]] = []

            # Search org-scoped analysis (DD chapters, macro reviews)
            try:
                org_chunks = search_fund_analysis_sync(
                    organization_id=str(org_id),
                    query_vector=query_vector,
                    instrument_id=payload.instrument_id,
                    top=15,
                )
                all_chunks.extend(org_chunks)
            except Exception as exc:
                logger.warning("Wealth agent: org-scoped search failed: %s", exc)

            # Search firm context (ADV brochures, manager profiles) if CRD/ESMA provided
            if payload.sec_crd or payload.esma_manager_id:
                try:
                    firm_chunks = search_fund_firm_context_sync(
                        query_vector=query_vector,
                        sec_crd=payload.sec_crd,
                        esma_manager_id=payload.esma_manager_id,
                        top=10,
                    )
                    all_chunks.extend(firm_chunks)
                except Exception as exc:
                    logger.warning("Wealth agent: firm context search failed: %s", exc)

            # Global fund search (no org filter — SEC/ESMA public data)
            if not payload.instrument_id:
                try:
                    from ai_engine.extraction.pgvector_search_service import search_esma_funds_sync

                    global_chunks = search_esma_funds_sync(
                        query_vector=query_vector,
                        top=10,
                    )
                    all_chunks.extend(global_chunks)
                except Exception as exc:
                    logger.warning("Wealth agent: global fund search failed: %s", exc)

            # Deduplicate by chunk id, sort by score
            seen: set[str] = set()
            unique_chunks: list[dict[str, Any]] = []
            for c in all_chunks:
                cid = str(c.get("id", ""))
                if cid in seen:
                    continue
                seen.add(cid)
                unique_chunks.append(c)
            unique_chunks.sort(key=lambda c: c.get("score", 0.0), reverse=True)
            unique_chunks = unique_chunks[:20]

            yield _sse("tool_call", {
                "tool": "vector_search",
                "status": "complete",
                "detail": f"Found {len(unique_chunks)} relevant chunks",
            })

            if not unique_chunks:
                yield _sse("chunk", {"text": "Insufficient evidence in the knowledge base to answer this question."})
                yield _sse("citations", {"citations": []})
                yield _sse("done", {})
                return

            # ── Step 3: Build prompt and call LLM ──
            yield _sse("tool_call", {"tool": "llm", "status": "running", "detail": "Generating answer…"})

            from ai_engine.model_config import get_model
            from ai_engine.openai_client import async_create_completion
            from ai_engine.prompts import prompt_registry

            # Serialize chunks for prompt
            chunks_text = "\n\n---\n\n".join(
                f"[{c.get('id', 'unknown')}] (source={c.get('source_type', 'unknown')}, "
                f"section={c.get('section', 'n/a')}, score={c.get('score', 0):.3f})\n"
                f"{(c.get('content', '') or '')[:1200]}"
                for c in unique_chunks
            )

            source_types = {c.get("source_type", "") for c in unique_chunks}

            runtime_context = ""
            if history_context:
                runtime_context += f"Conversation history:\n{history_context}\n\n"
            if payload.instrument_id:
                runtime_context += f"Scoped to instrument: {payload.instrument_id}\n"

            system_prompt = prompt_registry.render("services/wealth_agent_system.j2")
            user_prompt = prompt_registry.render(
                "services/wealth_agent_user.j2",
                question=question,
                chunks=chunks_text,
                chunk_count=len(unique_chunks),
                source_count=len(source_types),
                runtime_context=runtime_context or None,
            )

            result = await async_create_completion(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=get_model("policy"),
                temperature=0.2,
                max_tokens=4096,
                response_format={"type": "json_object"},
            )

            yield _sse("tool_call", {"tool": "llm", "status": "complete", "detail": "Answer generated"})

            # ── Step 4: Parse LLM response and stream answer ──
            raw = (result.text or "").strip()
            if raw.startswith("```"):
                raw = raw.strip("`").strip()
                if raw.lower().startswith("json"):
                    raw = raw[4:].strip()

            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                # If not valid JSON, treat the whole response as the answer
                obj = {"answer": raw, "citations": []}

            answer_text = str(obj.get("answer", "")).strip()
            citations = obj.get("citations", [])

            if not answer_text:
                answer_text = "Insufficient evidence in the knowledge base to answer this question."

            # Validate citations against retrieved chunks
            valid_chunk_ids = {str(c.get("id", "")) for c in unique_chunks}
            validated_citations = []
            for cite in citations:
                if isinstance(cite, dict) and str(cite.get("chunk_id", "")) in valid_chunk_ids:
                    validated_citations.append(cite)

            # If answer exists but no valid citations, reject it
            if answer_text != "Insufficient evidence in the knowledge base to answer this question." and not validated_citations:
                answer_text = "Insufficient evidence in the knowledge base to answer this question."
                validated_citations = []

            # Stream the answer as a single chunk (already fully generated)
            yield _sse("chunk", {"text": answer_text})
            yield _sse("citations", {"citations": validated_citations})
            yield _sse("done", {})

        except Exception as exc:
            logger.exception("Wealth agent error: %s", exc)
            yield _sse("error", {"message": "An error occurred while processing your request."})

    return EventSourceResponse(
        event_generator(),
        ping=15,
        ping_message_factory=lambda: ServerSentEvent(comment="keep-alive"),
    )
