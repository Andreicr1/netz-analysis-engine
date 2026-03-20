"""AI Copilot sub-router — activity, query, history, retrieve, answer."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import app.domains.credit.modules.ai.service as service
from ai_engine.openai_client import create_completion as _llm_completion
from ai_engine.prompts import prompt_registry
from app.core.db.audit import write_audit_event
from app.core.db.session import get_sync_db_with_rls
from app.core.middleware.audit import get_request_id
from app.core.security.clerk_auth import Actor, get_actor, require_readonly_allowed, require_roles
from app.domains.credit.ai.services.agent_context import AgentUIContext, build_agent_runtime_context
from app.domains.credit.ai.services.ai_scope import enforce_root_folder_scope
from app.domains.credit.modules.ai._helpers import (
    _blob_path_for_response,
    _limit,
    _offset,
)
from app.domains.credit.modules.ai.models import AIAnswer, AIAnswerCitation, AIQuestion
from app.domains.credit.modules.ai.schemas import (
    AIActivityItemOut,
    AIAnswerCitationOut,
    AIAnswerRequest,
    AIAnswerResponse,
    AIQueryCreate,
    AIQueryOut,
    AIRetrieveRequest,
    AIRetrieveResponse,
    AIRetrieveResult,
    Page,
)
from app.domains.credit.modules.documents.models import Document, DocumentChunk, DocumentVersion
from app.shared.enums import Role

router = APIRouter()


@router.get("/activity", response_model=Page[AIActivityItemOut])
def activity(
    fund_id: uuid.UUID,
    db: Session = Depends(get_sync_db_with_rls),
    limit: int = Depends(_limit),
    offset: int = Depends(_offset),
    _role_guard: Actor = Depends(require_roles([Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
) -> Page[AIActivityItemOut]:
    answers = list(
        db.execute(
            select(AIAnswer)
            .where(AIAnswer.fund_id == fund_id)
            .order_by(AIAnswer.created_at_utc.desc())
            .offset(offset)
            .limit(limit),
        )
        .scalars()
        .all(),
    )

    question_ids = [a.question_id for a in answers]
    by_q = {}
    if question_ids:
        qs = list(db.execute(select(AIQuestion).where(AIQuestion.fund_id == fund_id, AIQuestion.id.in_(question_ids))).scalars().all())
        by_q = {q.id: q for q in qs}

    answer_ids = [a.id for a in answers]
    citations_count_by_answer: dict[uuid.UUID, int] = {a.id: 0 for a in answers}
    if answer_ids:
        rows = list(
            db.execute(
                select(AIAnswerCitation.answer_id, func.count())
                .where(AIAnswerCitation.fund_id == fund_id, AIAnswerCitation.answer_id.in_(answer_ids))
                .group_by(AIAnswerCitation.answer_id),
            ).all(),
        )
        for aid, cnt in rows:
            citations_count_by_answer[aid] = int(cnt or 0)

    items: list[AIActivityItemOut] = []
    for a in answers:
        q = by_q.get(a.question_id)
        ans_text = a.answer_text or ""
        items.append(
            AIActivityItemOut(
                question_id=str(a.question_id),
                answer_id=str(a.id),
                question=q.question_text if q else None,
                asked_by=q.actor_id if q else None,
                timestamp_utc=a.created_at_utc,
                insufficient_evidence=ans_text == "Insufficient evidence in the Data Room",
                citations_count=int(citations_count_by_answer.get(a.id, 0)),
            ),
        )

    return Page(items=items, limit=limit, offset=offset)


@router.post("/query")
def create_query(
    fund_id: uuid.UUID,
    payload: AIQueryCreate,
    db: Session = Depends(get_sync_db_with_rls),
    actor: Actor = Depends(get_actor),
    _write_guard: Actor = Depends(require_readonly_allowed()),
):
    request_id = get_request_id() or "unknown"
    q, r = service.create_query_stub(db, fund_id=fund_id, actor=actor, payload=payload, request_id=request_id)
    return JSONResponse(
        status_code=501,
        content={
            "message": "AI query not implemented yet. Request persisted for auditability.",
            "ai_query_id": str(q.id),
            "ai_response_id": str(r.id),
            "request_id": request_id,
        },
    )


@router.get("/history", response_model=Page[AIQueryOut])
def history(
    fund_id: uuid.UUID,
    db: Session = Depends(get_sync_db_with_rls),
    limit: int = Depends(_limit),
    offset: int = Depends(_offset),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
) -> Page[AIQueryOut]:
    items = service.list_queries(db, fund_id=fund_id, limit=limit, offset=offset)
    return Page(items=items, limit=limit, offset=offset)


@router.post("/retrieve", response_model=AIRetrieveResponse)
def retrieve(
    fund_id: uuid.UUID,
    payload: AIRetrieveRequest,
    db: Session = Depends(get_sync_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_roles([Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
):
    request_id = get_request_id() or "unknown"

    try:
        enforce_root_folder_scope(actor=actor, requested_root_folder=payload.root_folder)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    write_audit_event(
        db,
        fund_id=fund_id,
        actor_id=actor.actor_id,
        action="AI_RETRIEVAL_QUERY",
        entity_type="fund",
        entity_id=str(fund_id),
        before=None,
        after={"query": payload.query, "root_folder": payload.root_folder, "top_k": payload.top_k, "request_id": request_id},
    )
    db.commit()

    # ── pgvector search + cross-encoder rerank ──────────────────────
    from ai_engine.extraction.embedding_service import generate_embeddings
    from ai_engine.extraction.pgvector_search_service import search_and_rerank_fund_sync

    if not actor.organization_id:
        raise HTTPException(status_code=403, detail="Organization context required")

    try:
        emb = generate_embeddings([payload.query])
        query_vector = emb.vectors[0] if emb.vectors else None
    except Exception:
        query_vector = None

    try:
        reranked_result = search_and_rerank_fund_sync(
            fund_id=fund_id,
            organization_id=actor.organization_id,
            query_text=payload.query,
            query_vector=query_vector,
            top=payload.top_k,
            candidates=payload.top_k * 3,
        )
        chunks = reranked_result.chunks
        retrieval_confidence = reranked_result.signal.confidence
    except Exception:
        raise HTTPException(status_code=502, detail="Search backend unavailable")

    # Join with Document/DocumentVersion for metadata
    doc_ids = list({c["doc_id"] for c in chunks if c.get("doc_id")})
    by_doc: dict[str, tuple[Document, DocumentVersion]] = {}
    if doc_ids:
        rows = (
            db.execute(
                select(Document, DocumentVersion)
                .join(DocumentVersion, DocumentVersion.document_id == Document.id)
                .where(
                    Document.fund_id == fund_id,
                    Document.id.in_([uuid.UUID(d) for d in doc_ids]),
                )
                .order_by(DocumentVersion.version_number.desc()),
            )
            .all()
        )
        for d, v in rows:
            if str(d.id) not in by_doc:
                by_doc[str(d.id)] = (d, v)

    # Filter by root_folder scope if requested
    if payload.root_folder:
        chunks = [
            c for c in chunks
            if c.get("doc_id") in by_doc
            and by_doc[c["doc_id"]][0].root_folder == payload.root_folder
        ]

    results: list[AIRetrieveResult] = []
    for c in chunks:
        pair = by_doc.get(c.get("doc_id", ""))
        content = (c.get("content") or "").strip()
        excerpt = content[:600] + ("..." if len(content) > 600 else "")
        if pair:
            d, v = pair
            results.append(
                AIRetrieveResult(
                    chunk_id=str(c["id"]),
                    document_title=d.title,
                    root_folder=d.root_folder,
                    folder_path=d.folder_path,
                    version_id=str(v.id),
                    version_number=int(v.version_number),
                    chunk_index=c.get("chunk_index"),
                    excerpt=excerpt,
                    source_blob=_blob_path_for_response(v),
                ),
            )
        else:
            results.append(
                AIRetrieveResult(
                    chunk_id=str(c["id"]),
                    document_title=c.get("title") or "Unknown",
                    root_folder=None,
                    folder_path=None,
                    version_id="",
                    version_number=0,
                    chunk_index=c.get("chunk_index"),
                    excerpt=excerpt,
                    source_blob=None,
                ),
            )

    write_audit_event(
        db,
        fund_id=fund_id,
        actor_id=actor.actor_id,
        action="AI_RETRIEVAL_RESULTS_RETURNED",
        entity_type="fund",
        entity_id=str(fund_id),
        before={"query": payload.query, "top_k": payload.top_k},
        after={"result_count": len(results), "chunk_ids": [r.chunk_id for r in results]},
    )
    db.commit()

    return AIRetrieveResponse(results=results, retrieval_confidence=retrieval_confidence)


@router.post("/answer", response_model=AIAnswerResponse)
def answer(
    fund_id: uuid.UUID,
    payload: AIAnswerRequest,
    db: Session = Depends(get_sync_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
):
    """Fund Copilot — RAG retrieval (pgvector + rerank) + LLM answer generation."""
    request_id = get_request_id() or "unknown"

    try:
        enforce_root_folder_scope(actor=actor, requested_root_folder=payload.root_folder)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    write_audit_event(
        db,
        fund_id=fund_id,
        actor_id=actor.actor_id,
        action="AI_ANSWER_REQUESTED",
        entity_type="fund",
        entity_id=str(fund_id),
        before=None,
        after={"question": payload.question, "root_folder": payload.root_folder, "top_k": payload.top_k, "request_id": request_id},
    )
    db.commit()

    # ── pgvector search + cross-encoder rerank ──────────────────────
    from ai_engine.extraction.embedding_service import generate_embeddings
    from ai_engine.extraction.pgvector_search_service import search_and_rerank_fund_sync

    if not actor.organization_id:
        raise HTTPException(status_code=403, detail="Organization context required")

    try:
        emb = generate_embeddings([payload.question])
        query_vector = emb.vectors[0] if emb.vectors else None
    except Exception:
        query_vector = None

    try:
        reranked_result = search_and_rerank_fund_sync(
            fund_id=fund_id,
            organization_id=actor.organization_id,
            query_text=payload.question,
            query_vector=query_vector,
            top=payload.top_k,
            candidates=payload.top_k * 3,
        )
        chunks = reranked_result.chunks
        retrieval_confidence = reranked_result.signal.confidence
    except Exception:
        raise HTTPException(status_code=502, detail="Search backend unavailable")

    retrieved_chunk_ids = [str(c["id"]) for c in chunks]

    q_row = AIQuestion(
        fund_id=fund_id,
        access_level="internal",
        actor_id=actor.actor_id,
        question_text=payload.question,
        root_folder=payload.root_folder,
        top_k=payload.top_k,
        request_id=request_id,
        retrieved_chunk_ids=retrieved_chunk_ids,
        created_by=actor.actor_id,
        updated_by=actor.actor_id,
    )
    db.add(q_row)
    db.flush()

    if not chunks:
        ans_text = "Insufficient evidence in the Data Room"
        a_row = AIAnswer(
            fund_id=fund_id,
            access_level="internal",
            question_id=q_row.id,
            model_version="no-evidence",
            answer_text=ans_text,
            prompt={"question": payload.question, "root_folder": payload.root_folder, "top_k": payload.top_k},
            created_by=actor.actor_id,
            updated_by=actor.actor_id,
        )
        db.add(a_row)
        db.flush()
        write_audit_event(
            db,
            fund_id=fund_id,
            actor_id=actor.actor_id,
            action="AI_INSUFFICIENT_EVIDENCE",
            entity_type="ai_question",
            entity_id=q_row.id,
            before=None,
            after={"reason": "no_retrieval_hits"},
        )
        db.commit()
        return AIAnswerResponse(answer=ans_text, citations=[])

    # Resolve Document metadata for enrichment + citations
    doc_ids = list({c["doc_id"] for c in chunks if c.get("doc_id")})
    by_doc: dict[str, tuple[Document, DocumentVersion]] = {}
    if doc_ids:
        rows = (
            db.execute(
                select(Document, DocumentVersion)
                .join(DocumentVersion, DocumentVersion.document_id == Document.id)
                .where(
                    Document.fund_id == fund_id,
                    Document.id.in_([uuid.UUID(d) for d in doc_ids]),
                )
                .order_by(DocumentVersion.version_number.desc()),
            )
            .all()
        )
        for d, v in rows:
            if str(d.id) not in by_doc:
                by_doc[str(d.id)] = (d, v)

    # Filter by root_folder scope if requested
    if payload.root_folder:
        chunks = [
            c for c in chunks
            if c.get("doc_id") in by_doc
            and by_doc[c["doc_id"]][0].root_folder == payload.root_folder
        ]

    # Build evidence items from pgvector content (no DocumentChunk dependency)
    evidence_items: list[dict] = []
    by_chunk_id: dict[str, dict] = {}
    for c in chunks:
        chunk_id = str(c["id"])
        content = (c.get("content") or "").strip()
        doc_pair = by_doc.get(c.get("doc_id", ""))
        item = {
            "chunk_id": chunk_id,
            "document_id": c.get("doc_id") or "",
            "version_id": str(doc_pair[1].id) if doc_pair else "",
            "title": doc_pair[0].title if doc_pair else (c.get("title") or "Unknown"),
            "root_folder": doc_pair[0].root_folder if doc_pair else None,
            "folder_path": doc_pair[0].folder_path if doc_pair else None,
            "page_start": c.get("page_start"),
            "page_end": c.get("page_end"),
            "excerpt": content[:800] + ("..." if len(content) > 800 else ""),
            "source_blob": _blob_path_for_response(doc_pair[1]) if doc_pair else None,
        }
        evidence_items.append(item)
        by_chunk_id[chunk_id] = item

    if not evidence_items:
        ans_text = "Insufficient evidence in the Data Room"
        a_row = AIAnswer(
            fund_id=fund_id,
            access_level="internal",
            question_id=q_row.id,
            model_version="missing-chunks",
            answer_text=ans_text,
            prompt={"question": payload.question, "root_folder": payload.root_folder, "top_k": payload.top_k},
            created_by=actor.actor_id,
            updated_by=actor.actor_id,
        )
        db.add(a_row)
        db.flush()
        write_audit_event(
            db,
            fund_id=fund_id,
            actor_id=actor.actor_id,
            action="AI_INSUFFICIENT_EVIDENCE",
            entity_type="ai_question",
            entity_id=q_row.id,
            before=None,
            after={"reason": "chunks_not_found_in_db"},
        )
        db.commit()
        return AIAnswerResponse(answer=ans_text, citations=[])

    runtime_context = build_agent_runtime_context(
        actor=actor,
        db=db,
        fund_id=fund_id,
        root_folder=payload.root_folder,
        ui_context=AgentUIContext(
            current_view=payload.current_view,
            entity_type=payload.entity_type,
            entity_id=payload.entity_id,
            entity_name=payload.entity_name,
            context_doc_title=payload.context_doc_title,
        ),
    )
    system_prompt = prompt_registry.render("services/copilot_system.j2")
    chunks_text = "\n\n".join(
        [
            f"- chunk_id: {e['chunk_id']}\n  title: {e['title']}\n  root_folder: {e['root_folder']}\n  folder_path: {e['folder_path']}\n  pages: {e['page_start']}-{e['page_end']}\n  excerpt: {e['excerpt']}"
            for e in evidence_items
        ],
    )
    source_count = len({e.get("root_folder") or "" for e in evidence_items})
    user_prompt = prompt_registry.render(
        "services/copilot_user.j2",
        question=payload.question,
        chunks=chunks_text,
        chunk_count=len(evidence_items),
        source_count=source_count,
        runtime_context=runtime_context,
    )

    try:
        import json as _json
        llm_result = _llm_completion(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.2,
            max_tokens=4096,
            response_format={"type": "json_object"},
        )
        _raw = (llm_result.text or "").strip()
        if _raw.startswith("```"):
            _raw = _raw.strip("`").strip()
            if _raw.lower().startswith("json"):
                _raw = _raw[4:].strip()
        obj = _json.loads(_raw)
        _llm_model = llm_result.model
    except Exception:
        raise HTTPException(status_code=502, detail="LLM backend unavailable")

    ans = str(obj.get("answer") or "").strip()
    cites = obj.get("citations") or []

    if not ans:
        ans = "Insufficient evidence in the Data Room"
    if ans != "Insufficient evidence in the Data Room" and (not isinstance(cites, list) or len(cites) == 0):
        write_audit_event(
            db,
            fund_id=fund_id,
            actor_id=actor.actor_id,
            action="AI_INSUFFICIENT_EVIDENCE",
            entity_type="ai_question",
            entity_id=q_row.id,
            before=None,
            after={"reason": "model_returned_no_citations"},
        )
        db.commit()
        return AIAnswerResponse(answer="Insufficient evidence in the Data Room", citations=[])

    # Match LLM-cited chunk_ids to our retrieved set
    cited_ids: list[str] = []
    for c in cites:
        if isinstance(c, dict) and c.get("chunk_id"):
            cited_ids.append(str(c["chunk_id"]))
    cited_ids = [cid for cid in cited_ids if cid in by_chunk_id]

    if ans != "Insufficient evidence in the Data Room" and len(cited_ids) == 0:
        write_audit_event(
            db,
            fund_id=fund_id,
            actor_id=actor.actor_id,
            action="AI_INSUFFICIENT_EVIDENCE",
            entity_type="ai_question",
            entity_id=q_row.id,
            before=None,
            after={"reason": "citations_not_in_retrieved_set"},
        )
        db.commit()
        return AIAnswerResponse(answer="Insufficient evidence in the Data Room", citations=[])

    a_row = AIAnswer(
        fund_id=fund_id,
        access_level="internal",
        question_id=q_row.id,
        model_version=f"openai-chat:{_llm_model}",
        answer_text=ans if ans else "Insufficient evidence in the Data Room",
        prompt={
            "system": system_prompt,
            "user": user_prompt,
            "runtime_context": runtime_context,
        },
        created_by=actor.actor_id,
        updated_by=actor.actor_id,
    )
    db.add(a_row)
    db.flush()

    # Build citation response; persist AIAnswerCitation only when DocumentChunk exists
    out_citations: list[AIAnswerCitationOut] = []
    for cid in cited_ids:
        item = by_chunk_id[cid]
        excerpt = item["excerpt"][:600] + ("..." if len(item["excerpt"]) > 600 else "")

        # Try to persist citation if Document metadata available
        doc_pair = by_doc.get(item.get("document_id", ""))
        if doc_pair:
            d, v = doc_pair
            # Find matching DocumentChunk for FK constraint
            dc_row = db.execute(
                select(DocumentChunk).where(
                    DocumentChunk.fund_id == fund_id,
                    DocumentChunk.document_id == d.id,
                    DocumentChunk.chunk_index == (item.get("page_start") or 0),
                ).limit(1),
            ).scalar_one_or_none()

            if dc_row:
                db.add(
                    AIAnswerCitation(
                        fund_id=fund_id,
                        access_level="internal",
                        answer_id=a_row.id,
                        chunk_id=dc_row.id,
                        document_id=d.id,
                        version_id=v.id,
                        page_start=item.get("page_start"),
                        page_end=item.get("page_end"),
                        excerpt=excerpt,
                        source_blob=item.get("source_blob"),
                        created_by=actor.actor_id,
                        updated_by=actor.actor_id,
                    ),
                )

        out_citations.append(
            AIAnswerCitationOut(
                chunk_id=cid,
                document_id=item.get("document_id") or "",
                version_id=item.get("version_id") or "",
                page_start=item.get("page_start"),
                page_end=item.get("page_end"),
                excerpt=excerpt,
                source_blob=item.get("source_blob"),
            ),
        )

    write_audit_event(
        db,
        fund_id=fund_id,
        actor_id=actor.actor_id,
        action="AI_ANSWER_RETURNED",
        entity_type="ai_answer",
        entity_id=a_row.id,
        before=None,
        after={"answer_len": len(ans), "citation_count": len(out_citations)},
    )
    db.commit()

    return AIAnswerResponse(answer=ans, citations=out_citations, retrieval_confidence=retrieval_confidence)
