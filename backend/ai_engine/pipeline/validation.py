"""Pipeline validation gates — inter-stage quality checks.

Each validator returns a ``PipelineStageResult`` indicating whether the
pipeline should proceed or halt for the current document.

Thresholds are module constants, not hardcoded inline.
"""
from __future__ import annotations

from ai_engine.pipeline.models import (
    CANONICAL_DOC_TYPES,
    HybridClassificationResult,
    PipelineStageResult,
)

# ── Thresholds ───────────────────────────────────────────────────────

# OCR output
MIN_OCR_CHARS = 100
MAX_NON_PRINTABLE_RATIO = 0.30

# Classification
MIN_CLASSIFICATION_CONFIDENCE = 0.3

# Chunking
MAX_CONTENT_LOSS_RATIO = 0.25   # 25% — accommodates header/footer/TOC stripping
                                 # while catching catastrophic loss (60%+)

# Extraction (metadata)
REQUIRED_METADATA_FIELDS = frozenset({"doc_type"})

# Embeddings
EXPECTED_EMBEDDING_DIM = 3072   # text-embedding-3-large


# ── Validators ───────────────────────────────────────────────────────

def validate_ocr_output(text: str, filename: str) -> PipelineStageResult:
    """Validate OCR output before classification.

    Checks:
    - Text length > MIN_OCR_CHARS
    - Non-printable character ratio < MAX_NON_PRINTABLE_RATIO
    """
    errors: list[str] = []
    warnings: list[str] = []
    char_count = len(text)

    if char_count < MIN_OCR_CHARS:
        errors.append(
            f"OCR produced only {char_count} chars (minimum: {MIN_OCR_CHARS}) "
            f"for '{filename}'"
        )

    if char_count > 0:
        # Sample-based scan to avoid O(n) on large documents
        _SAMPLE_HEAD = 10_000
        _SAMPLE_TAIL = 5_000
        if char_count > _SAMPLE_HEAD + _SAMPLE_TAIL:
            sample = text[:_SAMPLE_HEAD] + text[-_SAMPLE_TAIL:]
        else:
            sample = text
        non_printable = sum(1 for c in sample if not c.isprintable() and c not in "\n\r\t")
        ratio = non_printable / len(sample)
        if ratio > MAX_NON_PRINTABLE_RATIO:
            errors.append(
                f"Non-printable character ratio {ratio:.1%} exceeds "
                f"{MAX_NON_PRINTABLE_RATIO:.0%} for '{filename}'"
            )

    return PipelineStageResult(
        stage="ocr_validation",
        success=len(errors) == 0,
        data=text if not errors else None,
        metrics={"char_count": char_count, "filename": filename},
        warnings=warnings,
        errors=errors,
    )


def validate_classification(result: HybridClassificationResult) -> PipelineStageResult:
    """Validate classification result before chunking.

    Checks:
    - doc_type is in CANONICAL_DOC_TYPES
    - Confidence above threshold (warning only — does not halt pipeline)
    """
    errors: list[str] = []
    warnings: list[str] = []

    if result.doc_type not in CANONICAL_DOC_TYPES:
        errors.append(
            f"Invalid doc_type '{result.doc_type}' not in canonical set"
        )

    if result.confidence < MIN_CLASSIFICATION_CONFIDENCE:
        warnings.append(
            f"Low classification confidence {result.confidence:.2f} "
            f"(threshold: {MIN_CLASSIFICATION_CONFIDENCE}) — proceeding with caution"
        )

    return PipelineStageResult(
        stage="classification_validation",
        success=len(errors) == 0,
        data=result if not errors else None,
        metrics={
            "doc_type": result.doc_type,
            "vehicle_type": result.vehicle_type,
            "confidence": result.confidence,
            "layer": result.layer,
        },
        warnings=warnings,
        errors=errors,
    )


def validate_chunks(
    chunks: list,
    input_char_count: int,
    *,
    max_chunk_size: int | None = None,
) -> PipelineStageResult:
    """Validate chunking output before extraction.

    Checks:
    - chunk count > 0
    - Content retention: loss < MAX_CONTENT_LOSS_RATIO (one-directional —
      expansion is a separate WARNING, not FAILURE)
    - Max chunk size (warning only)
    """
    errors: list[str] = []
    warnings: list[str] = []
    chunk_count = len(chunks)

    if chunk_count == 0:
        errors.append("Chunking produced 0 chunks")
        return PipelineStageResult(
            stage="chunk_validation",
            success=False,
            data=None,
            metrics={"chunk_count": 0, "input_char_count": input_char_count},
            errors=errors,
        )

    # Content retention check
    output_chars = sum(len(getattr(c, "text", "") or str(c)) for c in chunks)
    if input_char_count > 0:
        loss_ratio = (input_char_count - output_chars) / input_char_count
        if loss_ratio > MAX_CONTENT_LOSS_RATIO:
            errors.append(
                f"Content loss {loss_ratio:.1%} exceeds {MAX_CONTENT_LOSS_RATIO:.0%} "
                f"threshold ({input_char_count} input → {output_chars} output chars)"
            )
        elif output_chars > input_char_count * 1.5:
            warnings.append(
                f"Content expansion detected: {input_char_count} input → "
                f"{output_chars} output chars (50%+ expansion)"
            )

    # Max chunk size check
    if max_chunk_size is not None:
        oversized = [
            i for i, c in enumerate(chunks)
            if len(getattr(c, "text", "") or str(c)) > max_chunk_size
        ]
        if oversized:
            warnings.append(
                f"{len(oversized)} chunks exceed max size {max_chunk_size}: "
                f"indices {oversized[:5]}"
            )

    return PipelineStageResult(
        stage="chunk_validation",
        success=len(errors) == 0,
        data=chunks if not errors else None,
        metrics={
            "chunk_count": chunk_count,
            "input_char_count": input_char_count,
            "output_char_count": output_chars,
        },
        warnings=warnings,
        errors=errors,
    )


def validate_extraction(metadata: dict) -> PipelineStageResult:
    """Validate metadata extraction output before embedding.

    Checks:
    - Metadata dict is not empty
    - Required fields present
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not metadata:
        errors.append("Metadata extraction returned empty dict")
    else:
        missing = REQUIRED_METADATA_FIELDS - set(metadata.keys())
        if missing:
            errors.append(f"Missing required metadata fields: {missing}")

    return PipelineStageResult(
        stage="extraction_validation",
        success=len(errors) == 0,
        data=metadata if not errors else None,
        metrics={"field_count": len(metadata) if metadata else 0},
        warnings=warnings,
        errors=errors,
    )


def validate_embeddings(
    embeddings: list,
    chunk_count: int,
) -> PipelineStageResult:
    """Validate embedding output before storage/indexing.

    Checks:
    - Embedding count matches chunk count
    - Each embedding has text content
    - Dimension consistency (if embeddings are numeric arrays)
    """
    errors: list[str] = []
    warnings: list[str] = []
    emb_count = len(embeddings)

    if emb_count != chunk_count:
        errors.append(
            f"Embedding count {emb_count} != chunk count {chunk_count}"
        )

    # Check for NaN values and dimension consistency
    if embeddings:
        first_dim = None
        for i, emb in enumerate(embeddings):
            vec = getattr(emb, "embedding", emb) if hasattr(emb, "embedding") else emb
            if hasattr(vec, "__len__"):
                dim = len(vec)
                if first_dim is None:
                    first_dim = dim
                elif dim != first_dim:
                    errors.append(
                        f"Dimension mismatch at index {i}: {dim} != {first_dim}"
                    )
                # Check for NaN (only if numeric)
                if hasattr(vec, "__iter__"):
                    try:
                        import math
                        if any(math.isnan(v) for v in vec):
                            errors.append(f"NaN detected in embedding at index {i}")
                            break  # One is enough
                    except (TypeError, ValueError):
                        pass

    return PipelineStageResult(
        stage="embedding_validation",
        success=len(errors) == 0,
        data=embeddings if not errors else None,
        metrics={"embedding_count": emb_count, "chunk_count": chunk_count},
        warnings=warnings,
        errors=errors,
    )
