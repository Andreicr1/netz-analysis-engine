from __future__ import annotations

from enum import Enum


class DocumentDomain(str, Enum):
    OFFERING = "OFFERING"
    AUDIT = "AUDIT"
    BANK = "BANK"
    KYC = "KYC"
    MANDATES = "MANDATES"
    CORPORATE = "CORPORATE"
    DEALS_MANAGERS = "DEALS_MANAGERS"
    MARKETING = "MARKETING"
    PROPOSALS = "PROPOSALS"
    ADMIN = "ADMIN"
    BOARD = "BOARD"
    INVESTMENT_MANAGER = "INVESTMENT_MANAGER"
    FEEDER = "FEEDER"
    OTHER = "OTHER"


class DocumentIngestionStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    INDEXED = "INDEXED"
    FAILED = "FAILED"

