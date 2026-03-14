import uuid

from pydantic import BaseModel, ConfigDict

from app.domains.credit.portfolio.enums import AlertSeverity, AlertType


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    asset_id: uuid.UUID
    obligation_id: uuid.UUID | None

    alert_type: AlertType
    severity: AlertSeverity

