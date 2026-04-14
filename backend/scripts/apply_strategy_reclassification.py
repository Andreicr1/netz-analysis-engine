"""Apply staged strategy reclassification to production.

Default mode is dry-run; ``--confirm`` is required to write. P2 (asset
class change) and P3 (lost class) additionally require ``--force``;
P3 further requires ``--justification`` (recorded on the audit event).

Examples
--------
Dry-run for full visibility::

    python backend/scripts/apply_strategy_reclassification.py --run-id <uuid> \\
        --severity all

Apply only safe additions (NULL → label)::

    python backend/scripts/apply_strategy_reclassification.py --run-id <uuid> \\
        --severity safe --confirm

Apply asset-class changes (requires --force)::

    python backend/scripts/apply_strategy_reclassification.py --run-id <uuid> \\
        --severity asset_class --confirm --force

Apply label removals (requires --force --justification)::

    python backend/scripts/apply_strategy_reclassification.py --run-id <uuid> \\
        --severity lost --confirm --force \\
        --justification "IC reviewed 2026-04-14 — esma residuals"

Idempotency / rollback
----------------------
Each invocation generates a single ``applied_batch_id`` UUID and stamps
every applied stage row with it. Re-running with the same severity is a
no-op because ``applied_at IS NOT NULL`` is excluded from the candidate
set. To rollback a batch, restore ``current_strategy_label`` from the
stage table; see ``docs/reference/classification-apply-runbook.md``.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.engine import async_session_factory as async_session
from app.domains.wealth.services.classification_family import (
    classify_severity,
    family_of,
)

logger = logging.getLogger("apply_strategy_reclassification")

# CLI alias → canonical severity tag from classification_family.Severity.
# ``all`` is a meta-token expanded at parse time.
SEVERITY_ALIASES: dict[str, str] = {
    "safe": "safe_auto_apply",
    "style": "style_refinement",
    "asset_class": "asset_class_change",
    "lost": "lost_class",
}
SEVERITIES_REQUIRING_FORCE: frozenset[str] = frozenset(
    {"asset_class_change", "lost_class"},
)
SEVERITIES_REQUIRING_JUSTIFICATION: frozenset[str] = frozenset({"lost_class"})

# Per-source UPDATE statements. Keyed by ``stage.source_table``. Each
# statement binds ``:label``, ``:source``, ``:pk`` and (for the JSONB
# variant) ``:ts``. The PK semantics differ per table — see the
# reclassification worker for details.
_UPDATE_STMTS: dict[str, str] = {
    "sec_manager_funds": """
        UPDATE sec_manager_funds
        SET strategy_label = :label,
            classification_source = :source,
            classification_updated_at = NOW()
        WHERE id::text = :pk
    """,
    "sec_registered_funds": """
        UPDATE sec_registered_funds
        SET strategy_label = :label,
            classification_source = :source,
            classification_updated_at = NOW()
        WHERE cik = :pk
    """,
    "sec_etfs": """
        UPDATE sec_etfs
        SET strategy_label = :label,
            classification_source = :source,
            classification_updated_at = NOW()
        WHERE series_id = :pk
    """,
    "sec_bdcs": """
        UPDATE sec_bdcs
        SET strategy_label = :label,
            classification_source = :source,
            classification_updated_at = NOW()
        WHERE series_id = :pk
    """,
    "sec_money_market_funds": """
        UPDATE sec_money_market_funds
        SET strategy_label = :label,
            classification_source = :source,
            classification_updated_at = NOW()
        WHERE series_id = :pk
    """,
    "esma_funds": """
        UPDATE esma_funds
        SET strategy_label = :label,
            classification_source = :source,
            classification_updated_at = NOW()
        WHERE isin = :pk
    """,
    # ``instruments_universe`` keeps its lineage inside the JSONB
    # ``attributes`` blob — the column-based pattern doesn't fit, but
    # the merge-and-store keeps the existing JSON-first invariant.
    "instruments_universe": """
        UPDATE instruments_universe
        SET attributes = COALESCE(attributes, '{}'::jsonb) || jsonb_build_object(
            'strategy_label', CAST(:label AS text),
            'classification_source', CAST(:source AS text),
            'classification_updated_at', CAST(:ts AS text)
        )
        WHERE instrument_id::text = :pk
    """,
}


def _resolve_severities(raw: str) -> list[str]:
    """Expand the ``--severity`` CLI value into canonical Severity tags."""
    requested = [s.strip() for s in raw.split(",") if s.strip()]
    if "all" in requested:
        return list(SEVERITY_ALIASES.values())
    out: list[str] = []
    for token in requested:
        canonical = SEVERITY_ALIASES.get(token)
        if canonical is None:
            raise SystemExit(
                f"Unknown severity: {token!r}. "
                f"Valid: {', '.join(sorted(SEVERITY_ALIASES))}, all",
            )
        out.append(canonical)
    return out


async def _apply_one(
    db: AsyncSession,
    *,
    row: Any,
    batch_id: UUID,
    actor: str,
) -> None:
    """Update the source table + mark the stage row applied."""
    source_table: str = row.source_table
    if source_table not in _UPDATE_STMTS:
        raise ValueError(f"Unknown source_table in stage: {source_table!r}")

    params: dict[str, Any] = {
        "label": row.proposed_strategy_label,
        "source": row.classification_source,
        "pk": row.source_pk,
    }
    if source_table == "instruments_universe":
        params["ts"] = datetime.now(timezone.utc).isoformat()

    await db.execute(text(_UPDATE_STMTS[source_table]), params)

    await db.execute(
        text(
            """
            UPDATE strategy_reclassification_stage
            SET applied_at       = NOW(),
                applied_by       = :actor,
                applied_batch_id = :batch_id
            WHERE stage_id = :stage_id
            """,
        ),
        {
            "actor": actor,
            "batch_id": str(batch_id),
            "stage_id": str(row.stage_id),
        },
    )


async def _emit_audit(
    db: AsyncSession,
    *,
    run_id: UUID,
    batch_id: UUID,
    actor: str,
    severities: list[str],
    counts: dict[str, int],
    justification: str | None,
) -> None:
    """Best-effort per-batch audit event.

    The audit table is RLS-scoped on ``organization_id``; a CLI invocation
    has no tenant context, so we attempt to write but log-and-skip if the
    row is rejected (e.g., NOT NULL on org_id). The script's structlog
    output remains the canonical record either way.
    """
    from app.core.db.audit import write_audit_event

    # SAVEPOINT isolates the audit insert. ``audit_events`` requires
    # ``organization_id`` NOT NULL; a CLI invocation has no RLS context
    # so the insert raises NotNullViolationError at flush time. Without
    # ``begin_nested`` that error poisons the outer transaction and
    # rolls back the production UPDATEs we just applied.
    try:
        async with db.begin_nested():
            await write_audit_event(
                db,
                actor_id=actor,
                action="apply_batch",
                entity_type="strategy_reclassification",
                entity_id=str(batch_id),
                after={
                    "run_id": str(run_id),
                    "batch_id": str(batch_id),
                    "severities": severities,
                    "counts": counts,
                    "justification": justification,
                    "applied_at": datetime.now(timezone.utc).isoformat(),
                    "legacy_taxonomy_migration": counts.get(
                        "legacy_to_canonical", 0,
                    ) > 0,
                },
            )
    except Exception as exc:
        logger.warning(
            "audit_event_skipped batch_id=%s reason=%s",
            batch_id, exc,
        )


def _is_legacy_to_canonical(
    current: str | None, proposed: str | None,
) -> bool:
    """A legacy → canonical migration is a P2 row where the current label
    is non-canonical (no family entry) and the proposed label is canonical.

    These ~21k rows were swept into ``asset_class_change`` by the original
    severity matrix only because ``unknown != equity`` (etc). They are
    vocabulary upgrades, not real cross-family reclassifications, and
    carry no information loss — the previous label was already off-taxonomy.
    """
    # ``current is not None`` excludes NULL→canonical (which is P0
    # safe_auto_apply, gated separately and never blocked by --force).
    return (
        current is not None
        and family_of(current) is None
        and proposed is not None
        and family_of(proposed) is not None
    )


async def apply_batch(
    run_id: UUID,
    severities: list[str],
    *,
    dry_run: bool,
    actor: str,
    justification: str | None,
    legacy_only: bool = False,
    source_filter: str | None = None,
) -> dict[str, int]:
    """Walk the stage table once; apply rows whose severity is selected.

    Idempotency guarantee: ``WHERE applied_at IS NULL`` filters out any
    row from a previous batch. Severity is computed *fresh* per row so a
    label that changed between report and apply is still gated correctly.

    Two narrowing filters can be combined with ``severities``:

    ``legacy_only``
        Only applies rows where ``current_family is None`` (current label
        not in canonical taxonomy) AND ``proposed_family is not None``.
        Use with ``--severity asset_class`` to migrate the legacy 37-label
        vocabulary into the canonical 51-label taxonomy without touching
        true cross-family changes. Counted as ``legacy_to_canonical``
        rather than under the underlying severity tag.

    ``source_filter``
        Only applies rows whose ``classification_source`` matches the
        given value (``fallback``, ``tiingo_description``, ``name_regex``,
        or ``adv_brochure``). Useful with ``--severity lost`` to apply
        only fallback-driven NULL transitions where the cascade had no
        signal to work with.
    """
    batch_id = uuid4()
    counts: dict[str, int] = dict.fromkeys(severities, 0)
    counts["legacy_to_canonical"] = 0
    counts["unchanged_skipped"] = 0
    counts["other_severity_skipped"] = 0
    counts["filtered_legacy"] = 0
    counts["filtered_source"] = 0
    counts["errors"] = 0

    async with async_session() as db:
        result = await db.execute(
            text(
                """
                SELECT stage_id, source_table, source_pk, fund_name,
                       current_strategy_label, proposed_strategy_label,
                       classification_source, confidence, matched_pattern
                FROM strategy_reclassification_stage
                WHERE run_id = :run_id
                  AND applied_at IS NULL
                """,
            ),
            {"run_id": str(run_id)},
        )
        rows = result.all()

        for row in rows:
            severity = classify_severity(
                row.current_strategy_label,
                row.proposed_strategy_label,
            )
            if severity == "unchanged":
                counts["unchanged_skipped"] += 1
                continue
            if severity not in severities:
                counts["other_severity_skipped"] += 1
                continue

            # ── Optional narrowing filters ───────────────────────────
            is_legacy = _is_legacy_to_canonical(
                row.current_strategy_label,
                row.proposed_strategy_label,
            )
            if legacy_only and not is_legacy:
                counts["filtered_legacy"] += 1
                continue
            if source_filter and row.classification_source != source_filter:
                counts["filtered_source"] += 1
                continue

            # Counter bucket: legacy_to_canonical takes precedence over
            # the raw severity tag so the operator sees the migration
            # signal in the result summary.
            counter_key = (
                "legacy_to_canonical"
                if (legacy_only and is_legacy)
                else severity
            )

            if dry_run:
                counts[counter_key] += 1
                continue
            try:
                await _apply_one(
                    db, row=row, batch_id=batch_id, actor=actor,
                )
                counts[counter_key] += 1
            except Exception as exc:
                logger.exception(
                    "apply_failed stage_id=%s source=%s pk=%s err=%s",
                    row.stage_id, row.source_table, row.source_pk, exc,
                )
                counts["errors"] += 1

        applied_total = (
            sum(counts[s] for s in severities)
            + counts["legacy_to_canonical"]
        )
        if not dry_run and applied_total > 0:
            await db.execute(
                text(
                    "REFRESH MATERIALIZED VIEW CONCURRENTLY mv_unified_funds",
                ),
            )
            logger.info("mv_unified_funds_refreshed batch_id=%s", batch_id)
            await _emit_audit(
                db,
                run_id=run_id,
                batch_id=batch_id,
                actor=actor,
                severities=severities,
                counts=counts,
                justification=justification,
            )
            await db.commit()
        elif not dry_run:
            # Nothing to apply; still commit any no-op stage writes (none
            # in practice, but explicit > implicit).
            await db.commit()

    counts["batch_id"] = str(batch_id)  # type: ignore[assignment]
    return counts


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, help="Stage run_id (UUID)")
    parser.add_argument(
        "--severity",
        required=True,
        help=(
            "Comma-separated severities: "
            "safe, style, asset_class, lost, all"
        ),
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Actually write to production (default is dry-run)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Required for asset_class and lost severities",
    )
    parser.add_argument(
        "--justification",
        default=None,
        help="Required for lost severity (recorded in audit event)",
    )
    parser.add_argument(
        "--actor",
        default=None,
        help="Operator name (default: $USER)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive 'APPLY' confirmation prompt (CI use)",
    )
    parser.add_argument(
        "--legacy-to-canonical-only",
        action="store_true",
        help=(
            "Only apply rows where the CURRENT label is non-canonical "
            "(unknown family) and the PROPOSED label is canonical. "
            "Treats them as a vocabulary migration: --force is NOT "
            "required even when severity is asset_class. Combine with "
            "--severity asset_class to migrate the legacy 37-label "
            "vocabulary into the 51-label canonical taxonomy."
        ),
    )
    parser.add_argument(
        "--source-filter",
        default=None,
        choices=("fallback", "tiingo_description", "name_regex", "adv_brochure"),
        help=(
            "Only apply rows whose classification_source matches. "
            "Most useful with '--severity lost --source-filter fallback' "
            "to apply only NULL transitions where the cascade had no "
            "signal at any layer."
        ),
    )
    return parser


async def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    severities = _resolve_severities(args.severity)

    # ``--legacy-to-canonical-only`` waives the --force gate for P2
    # because the operation is a vocabulary migration, not a real
    # asset-class reclassification (current label is off-taxonomy, no
    # information can be lost). lost_class still needs justification.
    needs_force = bool(
        set(severities) & SEVERITIES_REQUIRING_FORCE,
    ) and not args.legacy_to_canonical_only
    if needs_force and not args.force:
        parser.error(
            "--force is required when applying asset_class_change or "
            "lost_class. (Pass --legacy-to-canonical-only to waive "
            "--force for vocabulary migrations only.)",
        )
    needs_justification = bool(
        set(severities) & SEVERITIES_REQUIRING_JUSTIFICATION,
    )
    if needs_justification and not args.justification:
        parser.error(
            "--justification is required when applying lost_class",
        )
    if (
        args.legacy_to_canonical_only
        and "asset_class_change" not in severities
    ):
        parser.error(
            "--legacy-to-canonical-only only makes sense with "
            "--severity asset_class (or all)",
        )

    actor = args.actor or getpass.getuser()
    run_id = UUID(args.run_id)
    dry_run = not args.confirm

    print("apply_strategy_reclassification")
    print(f"  run_id            : {run_id}")
    print(f"  severities        : {', '.join(severities)}")
    print(f"  dry_run           : {dry_run}")
    print(f"  actor             : {actor}")
    if args.legacy_to_canonical_only:
        print("  legacy_only       : True (vocabulary migration mode)")
    if args.source_filter:
        print(f"  source_filter     : {args.source_filter}")
    if args.justification:
        print(f"  justification     : {args.justification}")
    print()

    if not dry_run and not args.yes:
        confirm = input("Type 'APPLY' to proceed: ").strip()
        if confirm != "APPLY":
            print("Aborted.")
            return

    counts = await apply_batch(
        run_id, severities,
        dry_run=dry_run,
        actor=actor,
        justification=args.justification,
        legacy_only=args.legacy_to_canonical_only,
        source_filter=args.source_filter,
    )

    print("\n=== RESULT ===")
    for key, value in counts.items():
        if isinstance(value, int):
            print(f"  {key}: {value:,}")
        else:
            print(f"  {key}: {value}")
    if dry_run:
        print("\n(dry-run — no changes persisted)")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(main())
