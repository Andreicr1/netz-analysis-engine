"""AI Copilot sub-router — activity, query, history, retrieve, answer."""
from __future__ import annotations

import functools
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
from app.domains.credit.ai.services.ai_scope import enforce_root_folder_scope, filter_hits_by_scope
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
from app.services.search_index import (
    AzureSearchChunksClient,
    RetrievalEmbeddingError,
    RetrievalExecutionError,
    RetrievalScopeError,
)
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

    try:
        client = AzureSearchChunksClient()
        # TODO(Phase 3 / Sprint 3): When AzureSearchChunksClient is implemented,
        # pass organization_id=str(actor.org_id) for tenant isolation (Security F2).
        hits = client.search(q=payload.query, fund_id=str(fund_id), root_folder=payload.root_folder, top=payload.top_k)
    except (RetrievalEmbeddingError, RetrievalExecutionError) as exc:
        raise HTTPException(status_code=502, detail=f"Search backend unavailable: {exc}")
    except RetrievalScopeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=502, detail="Search backend unavailable")

    hits = filter_hits_by_scope(actor=actor, hits=hits, get_root_folder=lambda h: getattr(h, "root_folder", None))

    version_ids = [uuid.UUID(h.version_id) for h in hits if h.version_id]
    if version_ids:
        rows = (
            db.execute(
                select(DocumentVersion, Document)
                .join(Document, Document.id == DocumentVersion.document_id)
                .where(
                    DocumentVersion.fund_id == fund_id,
                    Document.fund_id == fund_id,
                    DocumentVersion.id.in_(version_ids),
                ),
            )
            .all()
        )
        by_version: dict[uuid.UUID, tuple[DocumentVersion, Document]] = {r[0].id: (r[0], r[1]) for r in rows}
    else:
        by_version = {}

    results: list[AIRetrieveResult] = []
    for h in hits:
        vid = uuid.UUID(h.version_id) if h.version_id else None
        pair = by_version.get(vid) if vid else None
        if not pair:
            continue
        v, d = pair
        text = (h.content_text or "").strip()
        excerpt = text[:600] + ("..." if len(text) > 600 else "")
        results.append(
            AIRetrieveResult(
                chunk_id=h.chunk_id,
                document_title=d.title,
                root_folder=d.root_folder,
                folder_path=d.folder_path,
                version_id=str(v.id),
                version_number=int(v.version_number),
                chunk_index=h.chunk_index,
                excerpt=excerpt,
                source_blob=_blob_path_for_response(v),
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

    return AIRetrieveResponse(results=results)


@functools.lru_cache(maxsize=1)
@router.post("/answer", response_model=AIAnswerResponse)
def answer(
    fund_id: uuid.UUID,
    payload: AIAnswerRequest,
    db: Session = Depends(get_sync_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
):
    """Fund Copilot — RAG retrieval + LLM answer generation."""
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

    try:
        client = AzureSearchChunksClient()
        # TODO(Phase 3 / Sprint 3): When AzureSearchChunksClient is implemented,
        # pass organization_id=str(actor.org_id) for tenant isolation (Security F2).
        hits = client.search(q=payload.question, fund_id=str(fund_id), root_folder=payload.root_folder, top=payload.top_k)
    except (RetrievalEmbeddingError, RetrievalExecutionError) as exc:
        raise HTTPException(status_code=502, detail=f"Search backend unavailable: {exc}")
    except RetrievalScopeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=502, detail="Search backend unavailable")

    hits = filter_hits_by_scope(actor=actor, hits=hits, get_root_folder=lambda h: getattr(h, "root_folder", None))

    retrieved_chunk_ids = [h.chunk_id for h in hits if getattr(h, "chunk_id", None)]

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

    if not retrieved_chunk_ids:
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
        write_audit_event(
            db,
            fund_id=fund_id,
            actor_id=actor.actor_id,
            action="AI_ANSWER_RETURNED",
            entity_type="ai_answer",
            entity_id=a_row.id,
            before=None,
            after={"answer_len": len(ans_text), "citation_count": 0},
        )
        db.commit()
        # Evidence gap detection not implemented
        return AIAnswerResponse(answer=ans_text, citations=[])

    chunk_rows = (
        db.execute(
            select(DocumentChunk, DocumentVersion, Document)
            .join(DocumentVersion, DocumentVersion.id == DocumentChunk.version_id)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                DocumentChunk.fund_id == fund_id,
                DocumentVersion.fund_id == fund_id,
                Document.fund_id == fund_id,
                DocumentChunk.id.in_([uuid.UUID(x) for x in retrieved_chunk_ids]),
            ),
        )
        .all()
    )
    by_chunk_id = {str(r[0].id): (r[0], r[1], r[2]) for r in chunk_rows}

    evidence_items = []
    for cid in retrieved_chunk_ids:
        triple = by_chunk_id.get(cid)
        if not triple:
            continue
        c, v, d = triple
        evidence_items.append(
            {
                "chunk_id": str(c.id),
                "document_id": str(d.id),
                "version_id": str(v.id),
                "title": d.title,
                "root_folder": d.root_folder,
                "folder_path": d.folder_path,
                "page_start": c.page_start,
                "page_end": c.page_end,
                "excerpt": (c.text[:800] + ("..." if len(c.text) > 800 else "")),
                "source_blob": _blob_path_for_response(v),
            },
        )

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
        # Evidence gap detection not implemented
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
        # Evidence gap detection not implemented
        return AIAnswerResponse(answer="Insufficient evidence in the Data Room", citations=[])

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
        # Evidence gap detection not implemented
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

    out_citations: list[AIAnswerCitationOut] = []
    for cid in cited_ids:
        c_row, v_row, d_row = by_chunk_id[cid]
        excerpt = (c_row.text[:600] + ("..." if len(c_row.text) > 600 else ""))
        src = _blob_path_for_response(v_row)
        db.add(
            AIAnswerCitation(
                fund_id=fund_id,
                access_level="internal",
                answer_id=a_row.id,
                chunk_id=c_row.id,
                document_id=d_row.id,
                version_id=v_row.id,
                page_start=c_row.page_start,
                page_end=c_row.page_end,
                excerpt=excerpt,
                source_blob=src,
                created_by=actor.actor_id,
                updated_by=actor.actor_id,
            ),
        )
        out_citations.append(
            AIAnswerCitationOut(
                chunk_id=str(c_row.id),
                document_id=str(d_row.id),
                version_id=str(v_row.id),
                page_start=c_row.page_start,
                page_end=c_row.page_end,
                excerpt=excerpt,
                source_blob=src,
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

    return AIAnswerResponse(answer=ans, citations=out_citations)
