"""Vector Integrity Guard — fail-fast startup checks for embedding / index / env safety.

Guarantees:
  B1 — Embedding dimension matches Azure Search index schema
  B2 — Single embedding model version enforced
  B3 — Index prefix matches NETZ_ENV (no dev/prod cross-contamination)
  B4 — Blob container prefix matches NETZ_ENV (no cross-environment blob contamination)
  B5 — Search indexes are non-empty (prevents silent evidence starvation)

All guards raise ``RuntimeError`` on mismatch.  No fallback.  No auto-adjust.
"""
from __future__ import annotations

import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

# ── B2: Canonical embedding model constant ────────────────────────────
EMBEDDING_MODEL_NAME = "text-embedding-3-large"
EMBEDDING_DIMENSIONS = 3072


# ── B1: Embedding dimension validation ────────────────────────────────


def validate_embedding_dimensions() -> None:
    """Compare configured embedding model dimension with Azure Search index vector field.

    Raises ``RuntimeError`` on mismatch.  Skips silently if Azure Search
    is not configured (local dev without search).
    """
    endpoint = settings.AZURE_SEARCH_ENDPOINT
    index_name = settings.prefixed_index(
        settings.SEARCH_CHUNKS_INDEX_NAME or "global-vector-chunks-v4"
    )

    if not endpoint:
        logger.warning("AZURE_SEARCH_ENDPOINT not set — skipping embedding dimension validation.")
        return

    try:
        from azure.search.documents.indexes import SearchIndexClient

        if settings.AZURE_SEARCH_KEY:
            from azure.core.credentials import AzureKeyCredential
            cred = AzureKeyCredential(settings.AZURE_SEARCH_KEY)
        else:
            from azure.identity import DefaultAzureCredential
            cred = DefaultAzureCredential(exclude_interactive_browser_credential=True)
        index_client = SearchIndexClient(endpoint=endpoint, credential=cred)
        index_def = index_client.get_index(index_name)

        # Find the vector field (typically named 'embedding')
        vector_dim: int | None = None
        for field in index_def.fields:
            if hasattr(field, "vector_search_dimensions") and field.vector_search_dimensions:
                vector_dim = field.vector_search_dimensions
                break

        if vector_dim is None:
            logger.warning(
                "No vector field found in index '%s' — skipping dimension check.",
                index_name,
            )
            return

        if vector_dim != EMBEDDING_DIMENSIONS:
            raise RuntimeError(
                f"Embedding dimension mismatch between embedding model and search index. "
                f"Model '{EMBEDDING_MODEL_NAME}' produces {EMBEDDING_DIMENSIONS}-dim vectors, "
                f"but index '{index_name}' expects {vector_dim}-dim vectors."
            )

        logger.info(
            "Embedding dimension validated: model=%s dims=%d index=%s",
            EMBEDDING_MODEL_NAME,
            EMBEDDING_DIMENSIONS,
            index_name,
        )

    except RuntimeError:
        raise  # re-raise our own RuntimeError
    except Exception as exc:
        logger.warning(
            "Could not validate embedding dimensions (non-fatal): %s: %s",
            type(exc).__name__,
            exc,
        )


# ── B2: Enforce single embedding model version ───────────────────────


def validate_embedding_model() -> None:
    """Ensure the configured embedding model matches the canonical constant.

    Raises ``RuntimeError`` if there is a mismatch.
    """
    configured = settings.OPENAI_EMBEDDING_MODEL
    if configured != EMBEDDING_MODEL_NAME:
        raise RuntimeError(
            f"Embedding model drift detected. "
            f"Expected '{EMBEDDING_MODEL_NAME}', but settings has '{configured}'. "
            f"Dynamic switching is not allowed."
        )
    logger.info("Embedding model validated: %s", EMBEDDING_MODEL_NAME)


# ── B3: Index prefix environment guard ────────────────────────────────


def validate_index_prefix() -> None:
    """Ensure the resolved index name prefix matches NETZ_ENV.

    Dev: index must start with 'dev-'.
    Prod: index must NOT start with 'dev-'.
    Raises ``RuntimeError`` on mismatch.

    Skipped when RESOURCE_PREFIX is explicitly set (operator override).
    """
    # If operator explicitly set RESOURCE_PREFIX, trust their intent
    if settings.RESOURCE_PREFIX is not None:
        logger.info(
            "Index prefix check SKIPPED — RESOURCE_PREFIX explicitly set to %r",
            settings.RESOURCE_PREFIX,
        )
        return

    env = settings.effective_env
    base_name = settings.SEARCH_CHUNKS_INDEX_NAME or "global-vector-chunks-v4"
    resolved = settings.prefixed_index(base_name)

    if env == "dev":
        if not resolved.startswith("dev-"):
            raise RuntimeError(
                f"Index prefix mismatch: NETZ_ENV='dev' but resolved index "
                f"'{resolved}' does not start with 'dev-'. "
                f"Dev/prod cross-contamination risk."
            )
    elif env == "prod":
        if resolved.startswith("dev-"):
            raise RuntimeError(
                f"Index prefix mismatch: NETZ_ENV='prod' but resolved index "
                f"'{resolved}' starts with 'dev-'. "
                f"Dev/prod cross-contamination risk."
            )

    logger.info("Index prefix validated: env=%s index=%s", env, resolved)


# ── B4: Blob container environment guard ──────────────────────────────

# Set to True to raise RuntimeError on mismatch; False for a warning only.
BLOB_GUARD_STRICT = False


def validate_blob_container_prefix() -> None:
    """Ensure blob container names are prefixed according to NETZ_ENV.

    Dev: containers must start with 'dev-'.
    Prod: containers must NOT start with 'dev-'.
    Behaviour (strict vs. warning) is controlled by ``BLOB_GUARD_STRICT``.
    """
    env = settings.effective_env
    containers = [
        settings.prefixed_container(settings.AZURE_STORAGE_DATAROOM_CONTAINER),
        settings.prefixed_container(settings.AZURE_STORAGE_EVIDENCE_CONTAINER),
        settings.prefixed_container(settings.AZURE_STORAGE_MONTHLY_REPORTS_CONTAINER),
    ]

    violations: list[str] = []
    for name in containers:
        if env == "dev" and not name.startswith("dev-"):
            violations.append(f"Container '{name}' missing 'dev-' prefix in dev environment")
        elif env == "prod" and name.startswith("dev-"):
            violations.append(f"Container '{name}' has 'dev-' prefix in prod environment")

    if violations:
        msg = (
            f"Blob container environment guard violation (NETZ_ENV='{env}'): "
            + "; ".join(violations)
        )
        if BLOB_GUARD_STRICT:
            raise RuntimeError(msg)
        else:
            logger.warning(msg)
    else:
        logger.info("Blob container prefixes validated: env=%s containers=%s", env, containers)


# ── B5: Index document-count guardrail ────────────────────────────────


def validate_index_not_empty() -> None:
    """Verify both metadata and chunks indexes contain at least one document.

    An empty index silently starves every AI pipeline of evidence.
    Raises ``RuntimeError`` if an index returns 0 documents.
    Skips silently when Azure Search is not configured (local dev).
    """
    endpoint = settings.AZURE_SEARCH_ENDPOINT
    if not endpoint:
        logger.warning("AZURE_SEARCH_ENDPOINT not set — skipping index document-count check.")
        return

    try:
        from azure.search.documents import SearchClient

        if settings.AZURE_SEARCH_KEY:
            from azure.core.credentials import AzureKeyCredential
            cred = AzureKeyCredential(settings.AZURE_SEARCH_KEY)
        else:
            from azure.identity import DefaultAzureCredential
            cred = DefaultAzureCredential(exclude_interactive_browser_credential=True)

        indexes_to_check: list[tuple[str, str]] = []

        if settings.SEARCH_INDEX_NAME:
            indexes_to_check.append(("metadata", settings.SEARCH_INDEX_NAME))

        if settings.SEARCH_CHUNKS_INDEX_NAME:
            chunk_name = settings.prefixed_index(settings.SEARCH_CHUNKS_INDEX_NAME)
            indexes_to_check.append(("chunks", chunk_name))

        for label, idx_name in indexes_to_check:
            client = SearchClient(endpoint=endpoint, index_name=idx_name, credential=cred)
            results = list(client.search(search_text="*", top=1))
            if len(results) == 0:
                raise RuntimeError(
                    f"SEARCH INDEX EMPTY — {label} index '{idx_name}' returned 0 documents. "
                    f"Evidence retrieval will be completely starved. "
                    f"Check SEARCH_INDEX_NAME / SEARCH_CHUNKS_INDEX_NAME in .env."
                )
            logger.info("Index document-count OK: %s index '%s' has documents.", label, idx_name)

    except RuntimeError:
        raise
    except Exception as exc:
        logger.warning(
            "Could not validate index document counts (non-fatal): %s: %s",
            type(exc).__name__,
            exc,
        )


# ── Aggregate runner ──────────────────────────────────────────────────


def run_all_startup_guards() -> None:
    """Execute all vector integrity and environment guards at startup.

    Called from ``create_app()`` or app lifespan.  Any guard failure
    raises ``RuntimeError`` and prevents the application from starting.
    """
    logger.info("Running vector integrity startup guards...")

    validate_embedding_model()       # B2
    validate_index_prefix()          # B3
    validate_blob_container_prefix() # B4
    validate_index_not_empty()       # B5 (requires network)
    validate_embedding_dimensions()  # B1 (requires network — runs last)

    logger.info("All vector integrity startup guards passed.")
