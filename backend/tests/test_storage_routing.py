"""Tests for ai_engine.pipeline.storage_routing — path generation and validation."""
from __future__ import annotations

import uuid

import pytest

from ai_engine.pipeline.storage_routing import (
    _SAFE_PATH_SEGMENT_RE,
    _validate_segment,
    _validate_vertical,
    bronze_document_path,
    bronze_upload_blob_path,
    global_reference_path,
    gold_content_path,
    gold_dd_report_path,
    gold_fact_sheet_path,
    gold_memo_path,
    silver_chunks_glob,
    silver_chunks_path,
    silver_metadata_path,
)

ORG_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
FUND_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
VERSION_ID = uuid.UUID("66666666-7777-8888-9999-000000000000")


# ── _validate_segment ──────────────────────────────────────────────


class TestValidateSegment:
    def test_valid_alphanumeric(self):
        _validate_segment("abc123", "test")

    def test_valid_with_dash_underscore_dot(self):
        _validate_segment("my-file_name.v2", "test")

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            _validate_segment("", "label")

    def test_path_traversal_raises(self):
        with pytest.raises(ValueError, match="Invalid"):
            _validate_segment("../etc", "label")

    def test_space_raises(self):
        with pytest.raises(ValueError, match="Invalid"):
            _validate_segment("my file", "label")

    def test_special_chars_raise(self):
        for bad in ["foo/bar", "foo\\bar", "foo@bar", "foo bar", " leading"]:
            with pytest.raises(ValueError):
                _validate_segment(bad, "label")

    def test_starts_with_dot_raises(self):
        with pytest.raises(ValueError):
            _validate_segment(".hidden", "label")

    def test_starts_with_dash_raises(self):
        with pytest.raises(ValueError):
            _validate_segment("-flag", "label")


# ── _validate_vertical ────────────────────────────────────────────


class TestValidateVertical:
    def test_credit_ok(self):
        _validate_vertical("credit")

    def test_wealth_ok(self):
        _validate_vertical("wealth")

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="Invalid vertical"):
            _validate_vertical("equity")

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="Invalid vertical"):
            _validate_vertical("")


# ── bronze_document_path ──────────────────────────────────────────


class TestBronzeDocumentPath:
    def test_basic_path(self):
        result = bronze_document_path(ORG_ID, "credit", "doc123")
        assert result == f"bronze/{ORG_ID}/credit/documents/doc123.json"

    def test_wealth_vertical(self):
        result = bronze_document_path(ORG_ID, "wealth", "abc")
        assert result == f"bronze/{ORG_ID}/wealth/documents/abc.json"

    def test_invalid_vertical_raises(self):
        with pytest.raises(ValueError):
            bronze_document_path(ORG_ID, "invalid", "doc1")

    def test_path_traversal_doc_id_raises(self):
        with pytest.raises(ValueError):
            bronze_document_path(ORG_ID, "credit", "../secret")

    def test_empty_doc_id_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            bronze_document_path(ORG_ID, "credit", "")


# ── bronze_upload_blob_path ───────────────────────────────────────


class TestBronzeUploadBlobPath:
    def test_basic_path(self):
        result = bronze_upload_blob_path(ORG_ID, FUND_ID, VERSION_ID, "report.pdf")
        assert result == f"bronze/{ORG_ID}/{FUND_ID}/documents/{VERSION_ID}/report.pdf"

    def test_invalid_filename_raises(self):
        with pytest.raises(ValueError):
            bronze_upload_blob_path(ORG_ID, FUND_ID, VERSION_ID, "bad file.pdf")


# ── silver_chunks_path ────────────────────────────────────────────


class TestSilverChunksPath:
    def test_basic_path(self):
        result = silver_chunks_path(ORG_ID, "credit", "doc456")
        assert result == f"silver/{ORG_ID}/credit/chunks/doc456/chunks.parquet"

    def test_wealth_vertical(self):
        result = silver_chunks_path(ORG_ID, "wealth", "doc789")
        assert result == f"silver/{ORG_ID}/wealth/chunks/doc789/chunks.parquet"


# ── silver_metadata_path ─────────────────────────────────────────


class TestSilverMetadataPath:
    def test_basic_path(self):
        result = silver_metadata_path(ORG_ID, "credit", "doc111")
        assert result == f"silver/{ORG_ID}/credit/documents/doc111/metadata.json"


# ── silver_chunks_glob ────────────────────────────────────────────


class TestSilverChunksGlob:
    def test_glob_pattern(self):
        result = silver_chunks_glob(ORG_ID, "credit")
        assert result == f"silver/{ORG_ID}/credit/chunks/*/chunks.parquet"


# ── gold_memo_path ────────────────────────────────────────────────


class TestGoldMemoPath:
    def test_basic_path(self):
        result = gold_memo_path(ORG_ID, "credit", "memo001")
        assert result == f"gold/{ORG_ID}/credit/memos/memo001.json"

    def test_path_traversal_raises(self):
        with pytest.raises(ValueError):
            gold_memo_path(ORG_ID, "credit", "../hack")


# ── gold_fact_sheet_path ──────────────────────────────────────────


class TestGoldFactSheetPath:
    def test_basic_path(self):
        result = gold_fact_sheet_path(
            ORG_ID, "wealth", "port1", "2026-03-01", "pt", "factsheet.pdf",
        )
        assert result == f"gold/{ORG_ID}/wealth/fact_sheets/port1/2026-03-01/pt/factsheet.pdf"


# ── gold_content_path ────────────────────────────────────────────


class TestGoldContentPath:
    def test_basic_path(self):
        result = gold_content_path(ORG_ID, "wealth", "flash_report", "rpt1", "en")
        assert result == f"gold/{ORG_ID}/wealth/content/flash_report/rpt1/en/report.pdf"


# ── gold_dd_report_path ──────────────────────────────────────────


class TestGoldDdReportPath:
    def test_basic_path(self):
        result = gold_dd_report_path(ORG_ID, "wealth", "dd1", "pt")
        assert result == f"gold/{ORG_ID}/wealth/dd_reports/dd1/pt/report.pdf"


# ── global_reference_path ────────────────────────────────────────


class TestGlobalReferencePath:
    def test_basic_path(self):
        result = global_reference_path("fred_indicators", "gdp.parquet")
        assert result == "gold/_global/fred_indicators/gdp.parquet"

    def test_invalid_dataset_raises(self):
        with pytest.raises(ValueError):
            global_reference_path("../evil", "file.parquet")

    def test_invalid_filename_raises(self):
        with pytest.raises(ValueError):
            global_reference_path("fred", "bad file.csv")


# ── _SAFE_PATH_SEGMENT_RE ────────────────────────────────────────


class TestSafePathSegmentRegex:
    @pytest.mark.parametrize("segment", [
        "abc", "ABC123", "a1-b2", "file.pdf", "my_file", "a123-b456_c.txt",
    ])
    def test_valid_segments(self, segment: str):
        assert _SAFE_PATH_SEGMENT_RE.match(segment)

    @pytest.mark.parametrize("segment", [
        "", ".hidden", "-flag", " space", "a b", "../up", "foo/bar", "foo\\bar",
        "@mention", "#hash",
    ])
    def test_invalid_segments(self, segment: str):
        assert not _SAFE_PATH_SEGMENT_RE.match(segment)
