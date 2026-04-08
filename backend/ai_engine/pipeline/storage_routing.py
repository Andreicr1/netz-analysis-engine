"""ADLS path routing for bronze / silver / gold layers.

Builds deterministic paths following the convention:
  {tier}/{org_id}/{vertical}/...

Vertical comes from ``IngestRequest.vertical`` (request context),
NOT from classification output.

``_global/`` paths are for reference data (FRED, Yahoo, benchmarks)
with no org_id and no vertical.  Client documents NEVER go to ``_global/``.
"""
from __future__ import annotations

import re
from uuid import UUID

# Matches safe path segments: alphanumeric start, then alphanumeric/dot/dash/underscore.
_SAFE_PATH_SEGMENT_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._\-]*$")

_VALID_VERTICALS = frozenset({"credit", "wealth"})


def _validate_segment(value: str, label: str) -> None:
    """Validate a single path segment against traversal and injection."""
    if not value:
        raise ValueError(f"{label} must not be empty")
    if not _SAFE_PATH_SEGMENT_RE.match(value):
        raise ValueError(
            f"Invalid {label}: {value!r} — must match {_SAFE_PATH_SEGMENT_RE.pattern}",
        )


def _validate_vertical(vertical: str) -> None:
    if vertical not in _VALID_VERTICALS:
        raise ValueError(f"Invalid vertical: {vertical!r} — must be one of {_VALID_VERTICALS}")


# ── Bronze layer (raw ingested data) ───────────────────────────────


def bronze_upload_blob_path(
    org_id: UUID,
    fund_id: UUID,
    version_id: UUID,
    filename: str,
) -> str:
    """``bronze/{org_id}/{fund_id}/documents/{version_id}/{filename}``

    Stores the raw uploaded file blob (pre-OCR).  The fund_id acts as
    a namespace within the org, and version_id isolates revisions.
    """
    _validate_segment(str(fund_id), "fund_id")
    _validate_segment(str(version_id), "version_id")
    _validate_segment(filename, "filename")
    return f"bronze/{org_id}/{fund_id}/documents/{version_id}/{filename}"


def bronze_document_path(org_id: UUID, vertical: str, doc_id: str) -> str:
    """``bronze/{org_id}/{vertical}/documents/{doc_id}.json``

    Stores raw OCR output as JSON.
    """
    _validate_vertical(vertical)
    _validate_segment(doc_id, "doc_id")
    return f"bronze/{org_id}/{vertical}/documents/{doc_id}.json"


# ── Silver layer (processed / enriched data) ───────────────────────


def silver_chunks_path(org_id: UUID, vertical: str, doc_id: str) -> str:
    """``silver/{org_id}/{vertical}/chunks/{doc_id}/chunks.parquet``

    Stores chunked + embedded document data as Parquet.
    """
    _validate_vertical(vertical)
    _validate_segment(doc_id, "doc_id")
    return f"silver/{org_id}/{vertical}/chunks/{doc_id}/chunks.parquet"


def silver_metadata_path(org_id: UUID, vertical: str, doc_id: str) -> str:
    """``silver/{org_id}/{vertical}/documents/{doc_id}/metadata.json``

    Stores extracted metadata + summary as JSON.
    """
    _validate_vertical(vertical)
    _validate_segment(doc_id, "doc_id")
    return f"silver/{org_id}/{vertical}/documents/{doc_id}/metadata.json"


def silver_chunks_glob(org_id: UUID, vertical: str) -> str:
    """Glob pattern for all silver chunk Parquet files for a tenant.

    Used by DuckDBClient to scan the silver layer without enumerating
    individual document paths.
    """
    _validate_segment(str(org_id), "org_id")
    _validate_vertical(vertical)
    return f"silver/{org_id}/{vertical}/chunks/*/chunks.parquet"


# ── Gold layer (analytical outputs) ────────────────────────────────


def gold_memo_path(org_id: UUID, vertical: str, memo_id: str) -> str:
    """``gold/{org_id}/{vertical}/memos/{memo_id}.json``

    Stores IC memos and analytical reports.
    """
    _validate_vertical(vertical)
    _validate_segment(memo_id, "memo_id")
    return f"gold/{org_id}/{vertical}/memos/{memo_id}.json"


def gold_fact_sheet_path(
    org_id: UUID,
    vertical: str,
    portfolio_id: str,
    as_of_date: str,
    language: str,
    filename: str,
) -> str:
    """``gold/{org_id}/{vertical}/fact_sheets/{portfolio_id}/{as_of_date}/{language}/{filename}``

    Stores generated fact-sheet PDFs.  Language segment enables caching
    both PT and EN versions independently.
    """
    _validate_vertical(vertical)
    _validate_segment(portfolio_id, "portfolio_id")
    _validate_segment(as_of_date, "as_of_date")
    _validate_segment(language, "language")
    _validate_segment(filename, "filename")
    return (
        f"gold/{org_id}/{vertical}/fact_sheets/"
        f"{portfolio_id}/{as_of_date}/{language}/{filename}"
    )


def gold_content_path(
    org_id: UUID,
    vertical: str,
    content_type: str,
    content_id: str,
    language: str,
) -> str:
    """``gold/{org_id}/{vertical}/content/{content_type}/{content_id}/{language}/report.pdf``

    Stores generated content PDFs (investment outlooks, flash reports,
    manager spotlights).
    """
    _validate_vertical(vertical)
    _validate_segment(content_type, "content_type")
    _validate_segment(content_id, "content_id")
    _validate_segment(language, "language")
    return (
        f"gold/{org_id}/{vertical}/content/"
        f"{content_type}/{content_id}/{language}/report.pdf"
    )


def gold_dd_report_path(
    org_id: UUID,
    vertical: str,
    report_id: str,
    language: str,
) -> str:
    """``gold/{org_id}/{vertical}/dd_reports/{report_id}/{language}/report.pdf``

    Stores generated DD Report PDFs.
    """
    _validate_vertical(vertical)
    _validate_segment(report_id, "report_id")
    _validate_segment(language, "language")
    return f"gold/{org_id}/{vertical}/dd_reports/{report_id}/{language}/report.pdf"


def gold_monthly_report_path(
    org_id: UUID,
    portfolio_id: str,
    job_id: str,
) -> str:
    """``gold/{org_id}/wealth/reports/monthly-{portfolio_id}/{job_id}.pdf``

    Stores generated monthly client report PDFs for model portfolios.
    job_id provides uniqueness across multiple generations for the same
    portfolio (e.g., mcr-{portfolio_id}-{hex}).
    """
    _validate_segment(portfolio_id, "portfolio_id")
    _validate_segment(job_id, "job_id")
    return f"gold/{org_id}/wealth/reports/monthly-{portfolio_id}/{job_id}.pdf"


def gold_long_form_report_path(
    org_id: UUID,
    portfolio_id: str,
    job_id: str,
) -> str:
    """``gold/{org_id}/wealth/reports/long-form-dd-{portfolio_id}/{job_id}.pdf``

    Stores generated long-form due diligence report PDFs for model portfolios.
    job_id provides uniqueness across multiple generations.
    """
    _validate_segment(portfolio_id, "portfolio_id")
    _validate_segment(job_id, "job_id")
    return f"gold/{org_id}/wealth/reports/long-form-dd-{portfolio_id}/{job_id}.pdf"


def gold_library_bundle_path(org_id: UUID, bundle_id: str) -> str:
    """``gold/{org_id}/wealth/library/bundles/{bundle_id}/bundle.zip``

    Stores generated Wealth Library Committee Pack ZIPs (multi-document
    bundles produced on-demand by the ``library_bundle_builder`` worker).
    """
    _validate_segment(bundle_id, "bundle_id")
    return f"gold/{org_id}/wealth/library/bundles/{bundle_id}/bundle.zip"


def gold_library_bundle_manifest_path(org_id: UUID, bundle_id: str) -> str:
    """``gold/{org_id}/wealth/library/bundles/{bundle_id}/manifest.json``

    Stores the manifest JSON describing the contents of a library bundle.
    """
    _validate_segment(bundle_id, "bundle_id")
    return f"gold/{org_id}/wealth/library/bundles/{bundle_id}/manifest.json"


# ── Global paths (no org_id, no vertical) ──────────────────────────


# ── Credit-specific paths ─────────────────────────────────────────


def bronze_deal_path(org_id: UUID, deal_id: str, filename: str) -> str:
    """``bronze/{org_id}/credit/pipeline/deals/{deal_id}/{filename}``

    Stores deal-level documents and context JSON in the pipeline namespace.
    """
    _validate_segment(deal_id, "deal_id")
    _validate_segment(filename, "filename")
    return f"bronze/{org_id}/credit/pipeline/deals/{deal_id}/{filename}"


def gold_ic_memo_path(org_id: UUID, deal_id: str, filename: str) -> str:
    """``gold/{org_id}/credit/ic_memoranda/{deal_id}/{filename}``

    Stores IC memorandum PDFs generated by memo_chapters.
    """
    _validate_segment(deal_id, "deal_id")
    _validate_segment(filename, "filename")
    return f"gold/{org_id}/credit/ic_memoranda/{deal_id}/{filename}"


def gold_artifact_path(org_id: UUID, deal_id: str, filename: str) -> str:
    """``gold/{org_id}/credit/artifacts/{deal_id}/{filename}``

    Stores credit fund artifacts — fact sheets, marketing presentations.
    """
    _validate_segment(deal_id, "deal_id")
    _validate_segment(filename, "filename")
    return f"gold/{org_id}/credit/artifacts/{deal_id}/{filename}"


def gold_portfolio_review_path(org_id: UUID, investment_id: str, filename: str) -> str:
    """``gold/{org_id}/credit/portfolio_reviews/{investment_id}/{filename}``

    Stores periodic review PDFs for portfolio monitoring.
    """
    _validate_segment(investment_id, "investment_id")
    _validate_segment(filename, "filename")
    return f"gold/{org_id}/credit/portfolio_reviews/{investment_id}/{filename}"


def gold_credit_report_path(
    org_id: UUID,
    fund_id: str,
    report_type: str,
    filename: str,
) -> str:
    """``gold/{org_id}/credit/reports/{report_type}/{fund_id}/{filename}``

    Stores credit reporting outputs — monthly packs, investor statements.
    """
    _validate_segment(fund_id, "fund_id")
    _validate_segment(report_type, "report_type")
    _validate_segment(filename, "filename")
    return f"gold/{org_id}/credit/reports/{report_type}/{fund_id}/{filename}"


def global_reference_path(dataset: str, filename: str) -> str:
    """``gold/_global/{dataset}/{filename}``

    For reference data shared across all tenants: FRED indicators,
    ETF benchmarks, Yahoo Finance snapshots.
    """
    _validate_segment(dataset, "dataset")
    _validate_segment(filename, "filename")
    return f"gold/_global/{dataset}/{filename}"
