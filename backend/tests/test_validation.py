"""Tests for ai_engine.pipeline.validation — pipeline validation gates."""
from __future__ import annotations

from dataclasses import dataclass

from ai_engine.pipeline.models import HybridClassificationResult
from ai_engine.pipeline.validation import (
    MAX_CONTENT_LOSS_RATIO,
    MIN_CLASSIFICATION_CONFIDENCE,
    MIN_OCR_CHARS,
    validate_chunks,
    validate_classification,
    validate_embeddings,
    validate_ocr_output,
)

# ── validate_ocr_output ──────────────────────────────────────────


class TestValidateOcrOutput:
    def test_valid_text_passes(self):
        text = "A" * 200
        result = validate_ocr_output(text, "test.pdf")
        assert result.success is True
        assert result.data == text

    def test_short_text_fails(self):
        text = "short"
        result = validate_ocr_output(text, "test.pdf")
        assert result.success is False
        assert result.data is None
        assert any("chars" in e for e in result.errors)

    def test_empty_text_fails(self):
        result = validate_ocr_output("", "empty.pdf")
        assert result.success is False

    def test_exactly_min_chars_passes(self):
        text = "A" * MIN_OCR_CHARS
        result = validate_ocr_output(text, "test.pdf")
        assert result.success is True

    def test_one_below_min_fails(self):
        text = "A" * (MIN_OCR_CHARS - 1)
        result = validate_ocr_output(text, "test.pdf")
        assert result.success is False

    def test_high_non_printable_ratio_fails(self):
        # Build text that has >30% non-printable chars
        printable = "A" * 60
        non_printable = "\x00" * 50
        text = printable + non_printable + "B" * 50
        result = validate_ocr_output(text, "test.pdf")
        assert result.success is False
        assert any("Non-printable" in e for e in result.errors)

    def test_whitespace_chars_not_counted_as_non_printable(self):
        text = "A" * 100 + "\n" * 50 + "\t" * 50
        result = validate_ocr_output(text, "test.pdf")
        assert result.success is True

    def test_metrics_contain_char_count(self):
        text = "Hello world " * 20
        result = validate_ocr_output(text, "test.pdf")
        assert result.metrics["char_count"] == len(text)

    def test_large_text_uses_sampling(self):
        # Text > 15000 chars triggers head+tail sampling
        text = "A" * 20000
        result = validate_ocr_output(text, "large.pdf")
        assert result.success is True
        assert result.stage == "ocr_validation"


# ── validate_classification ───────────────────────────────────────


class TestValidateClassification:
    def _make_result(self, doc_type="legal_lpa", confidence=0.9, layer=1):
        return HybridClassificationResult(
            doc_type=doc_type,
            vehicle_type="standalone_fund",
            confidence=confidence,
            layer=layer,
            model_name="rules",
        )

    def test_valid_classification_passes(self):
        result = validate_classification(self._make_result())
        assert result.success is True

    def test_invalid_doc_type_fails(self):
        result = validate_classification(self._make_result(doc_type="not_a_type"))
        assert result.success is False
        assert any("Invalid doc_type" in e for e in result.errors)

    def test_low_confidence_warns_but_passes(self):
        result = validate_classification(self._make_result(confidence=0.1))
        assert result.success is True
        assert len(result.warnings) > 0
        assert any("Low classification" in w for w in result.warnings)

    def test_confidence_exactly_at_threshold(self):
        result = validate_classification(
            self._make_result(confidence=MIN_CLASSIFICATION_CONFIDENCE),
        )
        assert result.success is True
        assert len(result.warnings) == 0

    def test_confidence_just_below_threshold(self):
        result = validate_classification(
            self._make_result(confidence=MIN_CLASSIFICATION_CONFIDENCE - 0.01),
        )
        assert result.success is True
        assert len(result.warnings) > 0

    def test_metrics_contain_fields(self):
        r = self._make_result()
        result = validate_classification(r)
        assert result.metrics["doc_type"] == "legal_lpa"
        assert result.metrics["confidence"] == 0.9
        assert result.metrics["layer"] == 1


# ── validate_chunks ───────────────────────────────────────────────


@dataclass
class FakeChunk:
    text: str


class TestValidateChunks:
    def test_valid_chunks_pass(self):
        chunks = [FakeChunk(text="A" * 100) for _ in range(5)]
        result = validate_chunks(chunks, 500)
        assert result.success is True

    def test_empty_chunks_fail(self):
        result = validate_chunks([], 1000)
        assert result.success is False
        assert any("0 chunks" in e for e in result.errors)

    def test_high_content_loss_fails(self):
        # 1000 input chars, only 100 output chars = 90% loss
        chunks = [FakeChunk(text="A" * 100)]
        result = validate_chunks(chunks, 1000)
        assert result.success is False
        assert any("Content loss" in e for e in result.errors)

    def test_content_expansion_warns(self):
        # 100 input chars, 200 output = 100% expansion > 50%
        chunks = [FakeChunk(text="A" * 200)]
        result = validate_chunks(chunks, 100)
        assert result.success is True
        assert any("expansion" in w for w in result.warnings)

    def test_zero_input_chars_no_crash(self):
        chunks = [FakeChunk(text="some text")]
        result = validate_chunks(chunks, 0)
        assert result.success is True

    def test_oversized_chunks_warn(self):
        chunks = [FakeChunk(text="A" * 2000)]
        result = validate_chunks(chunks, 2000, max_chunk_size=500)
        assert result.success is True
        assert any("exceed max size" in w for w in result.warnings)

    def test_chunks_as_dicts_use_str(self):
        chunks = [{"content": "Hello world"}]
        result = validate_chunks(chunks, 20)
        assert result.success is True

    def test_metrics_contain_counts(self):
        chunks = [FakeChunk(text="A" * 50) for _ in range(3)]
        result = validate_chunks(chunks, 150)
        assert result.metrics["chunk_count"] == 3
        assert result.metrics["input_char_count"] == 150

    def test_content_loss_at_boundary(self):
        # Exactly at MAX_CONTENT_LOSS_RATIO should pass
        input_chars = 1000
        output_chars = int(input_chars * (1 - MAX_CONTENT_LOSS_RATIO))
        chunks = [FakeChunk(text="A" * output_chars)]
        result = validate_chunks(chunks, input_chars)
        assert result.success is True


# ── validate_embeddings ──────────────────────────────────────────


class TestValidateEmbeddings:
    def test_valid_embeddings_pass(self):
        embeddings = [[0.1] * 3072, [0.2] * 3072]
        result = validate_embeddings(embeddings, 2)
        assert result.success is True

    def test_count_mismatch_fails(self):
        embeddings = [[0.1] * 10]
        result = validate_embeddings(embeddings, 3)
        assert result.success is False
        assert any("count" in e for e in result.errors)

    def test_dimension_mismatch_fails(self):
        embeddings = [[0.1] * 10, [0.2] * 5]
        result = validate_embeddings(embeddings, 2)
        assert result.success is False
        assert any("Dimension mismatch" in e for e in result.errors)

    def test_nan_detected_fails(self):
        embeddings = [[0.1, float("nan"), 0.3]]
        result = validate_embeddings(embeddings, 1)
        assert result.success is False
        assert any("NaN" in e for e in result.errors)

    def test_empty_embeddings_with_zero_count_passes(self):
        result = validate_embeddings([], 0)
        assert result.success is True

    def test_consistent_dimensions_pass(self):
        embeddings = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6], [0.7, 0.8, 0.9]]
        result = validate_embeddings(embeddings, 3)
        assert result.success is True

    @dataclass
    class FakeEmbeddingObj:
        embedding: list[float]

    def test_embedding_objects_with_embedding_attr(self):
        embs = [
            self.FakeEmbeddingObj(embedding=[0.1, 0.2]),
            self.FakeEmbeddingObj(embedding=[0.3, 0.4]),
        ]
        result = validate_embeddings(embs, 2)
        assert result.success is True
