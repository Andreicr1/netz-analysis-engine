# GEMINI.md — Netz Analysis Engine Context for Google Antigravity

This file provides context for Gemini (LLM) when operating within the Antigravity IDE.

## Project Overview
Netz Analysis Engine is a unified multi-tenant analysis platform for institutional investment verticals (Private Credit and Wealth Management).

## Core Architecture
- **Backend**: Python 16 (FastAPI) with asyncpg.
- **Frontend**: SvelteKit 5 (Runes) for "Credit Intelligence" and "Wealth OS".
- **Database**: PostgreSQL 16 + TimescaleDB + pgvector (HNSW index).
- **AI Engine**: Hybrid classification (Rules + Cosine Similarity + LLM), RAG via pgvector, and structured extraction.
- **Quant Engine**: Portfolio optimization (CLARABEL), GARCH volatility, and Black-Litterman returns.

## Development Standards
- **Async-first**: All backend routes and I/O are asynchronous.
- **Strict Typing**: Pydantic v2 for schemas, Mypy for type checking.
- **Vertical Isolation**: `vertical_engines/credit` and `vertical_engines/wealth` must not cross-import.
- **Tenancy**: Multi-tenant via `organization_id` and PostgreSQL RLS.

## Key Directories
- `backend/app/domains/`: Vertical-specific API routes.
- `backend/ai_engine/`: Domain-agnostic AI infrastructure (ingestion, classification, embedding).
- `backend/vertical_engines/`: Specialized analysis logic for Credit and Wealth.
- `frontends/`: SvelteKit applications.
- `docs/`: Technical specifications and plans.

## Gemini Roles
Gemini is used for:
1. **Document Intelligence**: Classifying and extracting metadata from financial PDFs.
2. **Content Generation**: Drafting IC Memorandums and DD Reports.
3. **Fund Copilot**: Providing RAG-based answers about investment portfolios.
4. **Code Assistance**: Helping maintain this repository's standards.

## Troubleshooting Antigravity Chat
If Gemini Chat in Antigravity is not responding correctly:
1. Ensure this `GEMINI.md` is indexed.
2. Check `CLAUDE.md` for broader project commands and architecture.
3. Verify that the current file context is within the supported verticals.
