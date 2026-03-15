"""KYC Pipeline Screening — automated KYC Spider checks for Deep Review.

Public API:
    run_kyc_screenings()            — run all screenings (never raises)
    build_kyc_appendix()            — format results as Markdown appendix
    persist_kyc_screenings_to_db()  — persist to DB (optional, stubs)

Error contract: never-raises (orchestration engine called during deep review).
Returns dict with summary.skipped=True on failure.
"""
from vertical_engines.credit.kyc.appendix import build_kyc_appendix
from vertical_engines.credit.kyc.persistence import persist_kyc_screenings_to_db
from vertical_engines.credit.kyc.service import run_kyc_screenings

__all__ = [
    "run_kyc_screenings",
    "build_kyc_appendix",
    "persist_kyc_screenings_to_db",
]
