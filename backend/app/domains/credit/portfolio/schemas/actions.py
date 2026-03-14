import uuid

from pydantic import BaseModel, ConfigDict

from app.domains.credit.portfolio.enums import ActionStatus


class ActionCreate(BaseModel):
    title: str
    evidence_required: bool = True
    evidence_notes: str | None = None


class ActionUpdate(BaseModel):
    status: ActionStatus
    evidence_notes: str | None = None


class ActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    asset_id: uuid.UUID
    alert_id: uuid.UUID

    title: str
    status: ActionStatus
    evidence_required: bool
    evidence_notes: str | None

