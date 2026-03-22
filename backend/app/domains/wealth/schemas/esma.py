"""Pydantic schemas for ESMA UCITS endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class EsmaManagerItem(BaseModel):
    esma_id: str
    company_name: str
    country: str | None = None
    authorization_status: str | None = None
    sec_crd_number: str | None = None
    fund_count: int = 0


class EsmaManagerPage(BaseModel):
    items: list[EsmaManagerItem]
    total: int
    page: int
    page_size: int


class EsmaFundItem(BaseModel):
    isin: str
    fund_name: str
    domicile: str | None = None
    fund_type: str | None = None
    yahoo_ticker: str | None = None
    esma_manager_id: str | None = None


class EsmaFundPage(BaseModel):
    items: list[EsmaFundItem]
    total: int
    page: int
    page_size: int


class EsmaManagerDetail(BaseModel):
    esma_id: str
    company_name: str
    country: str | None = None
    authorization_status: str | None = None
    sec_crd_number: str | None = None
    funds: list[EsmaFundItem] = []


class EsmaFundDetail(BaseModel):
    isin: str
    fund_name: str
    domicile: str | None = None
    fund_type: str | None = None
    yahoo_ticker: str | None = None
    manager: EsmaManagerItem | None = None


class EsmaSecCrossRef(BaseModel):
    esma_id: str
    sec_crd_number: str | None = None
    sec_firm_name: str | None = None
    matched: bool = False
