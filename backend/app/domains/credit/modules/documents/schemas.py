from __future__ import annotations

import datetime as dt
import uuid
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.domains.credit.documents.enums import DocumentDomain

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    limit: int
    offset: int


class DocumentCreate(BaseModel):
    document_type: str = Field(min_length=2, max_length=100)
    title: str = Field(min_length=2, max_length=300)
    status: str = Field(default="draft", max_length=32)
    meta: dict | None = Field(default=None, validation_alias="metadata", serialization_alias="metadata")


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fund_id: uuid.UUID
    access_level: str
    source: str | None = None
    document_type: str
    title: str
    status: str
    current_version: int
    root_folder: str | None = None
    folder_path: str | None = None
    domain: DocumentDomain | None = None
    blob_uri: str | None = None
    meta: dict | None = Field(default=None, serialization_alias="metadata")
    created_at: dt.datetime
    updated_at: dt.datetime


class DocumentVersionCreate(BaseModel):
    version_number: int = Field(ge=1)
    blob_uri: str | None = Field(default=None, max_length=800)
    checksum: str | None = Field(default=None, max_length=128)
    file_size_bytes: int | None = None
    is_final: bool = False
    meta: dict | None = Field(default=None, validation_alias="metadata", serialization_alias="metadata")


class DocumentVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fund_id: uuid.UUID
    access_level: str
    document_id: uuid.UUID
    version_number: int
    blob_uri: str | None
    blob_path: str | None = None
    checksum: str | None
    file_size_bytes: int | None
    is_final: bool
    uploaded_by: str | None = None
    uploaded_at: dt.datetime | None = None
    meta: dict | None = Field(default=None, serialization_alias="metadata")
    created_at: dt.datetime
    updated_at: dt.datetime

