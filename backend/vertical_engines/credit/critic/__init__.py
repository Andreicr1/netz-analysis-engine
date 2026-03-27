"""IC Critic Engine — adversarial review of deal intelligence and memos.

Public API:
    critique_intelligence()     — run adversarial IC critique (never raises)
    build_critic_packet()       — build compressed IC packet for critic
    classify_instrument_type()  — deterministic instrument classification
    CriticVerdict               — result dataclass
    INSTRUMENT_TYPE_PROFILES    — instrument-aware fatal flaw criteria

Error contract: never-raises (orchestration engine called during deep review).
Returns CriticVerdict with overall_assessment='NOT_ASSESSED' on failure.
"""
from vertical_engines.credit.critic.classifier import classify_instrument_type
from vertical_engines.credit.critic.models import (
    INSTRUMENT_TYPE_PROFILES,
    CriticVerdict,
)
from vertical_engines.credit.critic.service import (
    build_critic_packet,
    critique_intelligence,
)

__all__ = [
    "INSTRUMENT_TYPE_PROFILES",
    "CriticVerdict",
    "build_critic_packet",
    "classify_instrument_type",
    "critique_intelligence",
]
