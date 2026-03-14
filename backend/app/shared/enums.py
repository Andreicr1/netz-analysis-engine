"""Shared enums used across all domains."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "ADMIN"
    INVESTMENT_TEAM = "INVESTMENT_TEAM"
    GP = "GP"
    DIRECTOR = "DIRECTOR"
    COMPLIANCE = "COMPLIANCE"
    AUDITOR = "AUDITOR"
    INVESTOR = "INVESTOR"
    ADVISOR = "ADVISOR"


READONLY_ROLES: frozenset[Role] = frozenset({Role.INVESTOR, Role.AUDITOR, Role.ADVISOR})
