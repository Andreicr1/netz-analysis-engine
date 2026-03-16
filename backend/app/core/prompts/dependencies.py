"""FastAPI dependencies for PromptService."""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.prompts.prompt_service import PromptService
from app.core.tenancy.middleware import get_db_with_rls


async def get_prompt_service(
    db: AsyncSession = Depends(get_db_with_rls),
) -> PromptService:
    """Inject PromptService with RLS-aware session."""
    return PromptService(db=db)
