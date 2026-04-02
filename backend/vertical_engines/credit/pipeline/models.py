"""Pipeline intelligence models and constants (LEAF — zero sibling imports).

All constants, configuration values, and type aliases used across the
pipeline package. This module has NO imports from sibling modules.
"""
from __future__ import annotations

# ── Intelligence status constants ─────────────────────────────────────

STATUS_PENDING = "PENDING"
STATUS_PROCESSING = "PROCESSING"
STATUS_READY = "READY"
STATUS_FAILED = "FAILED"

# ── Evidence surface configuration (Tier-1) ───────────────────────────

MAX_RETRIEVAL_CHUNKS = 80
MAX_CHARS_PER_CHUNK = 4_000
MIN_CITATIONS_REQUIRED = 5
MIN_MEMO_CHARS = 2_000
MIN_KEY_RISKS = 3

# ── Pipeline container ────────────────────────────────────────────────

PIPELINE_CONTAINER = "investment-pipeline-intelligence"

# ── Risk ordering ─────────────────────────────────────────────────────

RISK_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
RISK_BAND_ORDER = {"LOW": 1, "MODERATE": 2, "HIGH": 3, "SPECULATIVE": 4}

# ── Document type map ─────────────────────────────────────────────────

DOC_TYPE_MAP: dict[str, tuple[str, int]] = {
    "INVESTMENT_MEMO": ("Investment Memo", 92),
    "DEAL_MARKETING": ("Marketing Deck", 82),
    "FUND_CONSTITUTIONAL": ("Legal Draft", 76),
    "SERVICE_PROVIDER_CONTRACT": ("Legal Draft", 84),
    "AUDIT_EVIDENCE": ("Due Diligence Report", 80),
    "REGULATORY_CIMA": ("Legal Draft", 70),
    "OTHER": ("Term Sheet", 60),
}

# ── Standard DD document types (weighted for completeness scoring) ────

REQUIRED_DD_DOCUMENTS = [
    {"document_type": "Audited Financial Statements", "priority": "critical", "weight": 15,
     "reason": "Required for underwriting leverage, debt service coverage, and default risk assessment"},
    {"document_type": "Tax Returns (2-3 years)", "priority": "critical", "weight": 12,
     "reason": "Validates reported financial performance and identifies off-balance-sheet liabilities"},
    {"document_type": "Credit Agreement / Loan Documentation", "priority": "critical", "weight": 15,
     "reason": "Defines terms, covenants, security package, events of default, and waterfall mechanics"},
    {"document_type": "Collateral Valuation / Appraisal", "priority": "critical", "weight": 12,
     "reason": "Determines recovery value in downside/enforcement scenarios"},
    {"document_type": "Management Accounts (Trailing 12 Months)", "priority": "high", "weight": 10,
     "reason": "Provides current-period financial visibility beyond last audit date"},
    {"document_type": "Organizational Documents (LLC/LP Agreement)", "priority": "high", "weight": 8,
     "reason": "Confirms legal structure, authority to borrow, and decision-making governance"},
    {"document_type": "Insurance Certificates", "priority": "high", "weight": 7,
     "reason": "Validates coverage of key collateral and business interruption risks"},
    {"document_type": "Environmental / Regulatory Compliance Reports", "priority": "medium", "weight": 5,
     "reason": "Identifies contingent liabilities and regulatory enforcement risk"},
    {"document_type": "Borrower Corporate Presentation / CIM", "priority": "medium", "weight": 5,
     "reason": "Provides business model context, competitive positioning, and growth strategy"},
    {"document_type": "UCC / Lien Search Results", "priority": "high", "weight": 11,
     "reason": "Confirms priority of security interest and identifies competing claims"},
]

TOTAL_DD_WEIGHT: int = sum(int(d["weight"]) for d in REQUIRED_DD_DOCUMENTS)
