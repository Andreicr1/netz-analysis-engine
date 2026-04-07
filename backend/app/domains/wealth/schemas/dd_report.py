"""DD Report Pydantic schemas for API serialization.

`DDChapterRead.quant_data` is a free-form dict produced by the DD
pipeline chapter engines. Raw metric keys (`cvar_95`, `max_drawdown`,
`garch_volatility`, …) are translated into the Risk Methodology v3
institutional labels by the Wealth sanitation layer before the
chapter reaches the API boundary. See the charter in
`app.domains.wealth.schemas.sanitized`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domains.wealth.schemas.sanitized import sanitize_dict_keys


class DDChapterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: uuid.UUID
    chapter_tag: str
    chapter_order: int
    content_md: str | None = None
    evidence_refs: dict | None = None
    quant_data: dict | None = None
    critic_iterations: int
    critic_status: str
    generated_at: datetime | None = None

    @model_validator(mode="after")
    def _sanitize_quant_data(self) -> DDChapterRead:
        # `quant_data` flattens to the evidence grid in the DD report
        # reading workbench — its dict keys are rendered verbatim. We
        # translate the keys here so the frontend never needs to know
        # the raw backend metric identifiers.
        if isinstance(self.quant_data, dict):
            object.__setattr__(
                self,
                "quant_data",
                sanitize_dict_keys(self.quant_data),
            )
        return self


class DDReportSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: uuid.UUID
    instrument_id: uuid.UUID
    report_type: str = "dd_report"
    version: int
    status: str
    confidence_score: Decimal | None = None
    decision_anchor: str | None = None
    is_current: bool
    created_at: datetime
    created_by: str | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    rejection_reason: str | None = None
    storage_path: str | None = None
    pdf_language: str | None = None


class DDReportRead(DDReportSummary):
    config_snapshot: dict | None = None
    schema_version: int
    chapters: list[DDChapterRead] = []


class DDReportListItem(DDReportSummary):
    """Extended summary with instrument name for the all-reports listing."""

    instrument_name: str = ""
    instrument_ticker: str | None = None


class DDReportCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    config_overrides: dict | None = None


class DDReportRejectRequest(BaseModel):
    reason: str = Field(..., min_length=10, max_length=2000)


class DDReportApproveRequest(BaseModel):
    rationale: str = Field(..., min_length=10, max_length=2000)


class DDReportRegenerate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    chapter_tags: list[str] | None = None


class AuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    action: str
    actor_id: str | None
    before: dict | None
    after: dict | None
    created_at: str | None
