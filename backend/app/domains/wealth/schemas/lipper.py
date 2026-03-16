"""Pydantic schemas for Lipper fund ratings."""

from datetime import date

from pydantic import BaseModel, ConfigDict, field_validator


class LipperRatingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    fund_id: str
    rating_date: date
    overall_rating: int | None = None
    consistent_return: int | None = None
    preservation: int | None = None
    total_return: int | None = None
    expense: int | None = None
    tax_efficiency: int | None = None
    fund_classification: str | None = None

    @field_validator(
        "overall_rating", "consistent_return", "preservation",
        "total_return", "expense", "tax_efficiency",
        mode="before",
    )
    @classmethod
    def check_range(cls, v: int | None) -> int | None:
        if v is not None and not (1 <= v <= 5):
            raise ValueError("Lipper rating must be between 1 and 5")
        return v
