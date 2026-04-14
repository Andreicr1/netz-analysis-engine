# Classification Phase 2 — Session B: Diff Gate + Apply Script

**Date:** 2026-04-14
**Branch:** `feat/classification-apply-gate`
**Sessions:** 1 (two sub-steps: report generation + apply script)
**Depends on:** PRs #168, #169, #171, #172, #173 merged; Round 2 staging run `b5623a5b-9f2d-4df7-b02f-0726a9703ea8` populated

---

## Context

After Round 1 + Round 2 classifier patches + universe sanitization, the staging table contains 84,212 proposed classifications under `run_id = b5623a5b-9f2d-4df7-b02f-0726a9703ea8`. None have been applied to production. Every day in staging is a day where screener, scoring, peer groups, and allocation blocks operate on stale labels.

This sprint delivers the apply gate — the controlled, severity-tiered mechanism to move proposed labels into production with operator oversight. No auto-apply without explicit confirmation. Lineage preserved. Rollback possible via staging history.

**Empirical numbers to calibrate:**

| Severity tier | Count | Risk | Default behavior |
|---|---|---|---|
| P0 safe_auto_apply | ~1,400 | None (NULL → specific) | Apply with `--confirm`, no force needed |
| P1 style_refinement | ~5,000 | Low (same family) | Apply with `--confirm` |
| P2 asset_class_change | ~13,000 | Medium (different family) | Require `--confirm --force` |
| P3 lost_class | ~9,600 | High (current non-null → NULL) | Require `--confirm --force --justification` |
| unchanged | ~55,000 | None | Never applied (no-op) |

---

## OBJECTIVE

1. Extend source tables with `classification_source` + `classification_updated_at` for lineage.
2. Generate a structured diff CSV with severity classification, family change detection, and downstream impact.
3. Apply staged labels to production in controlled batches via severity filter.
4. Preserve rollback capability (stage retains `current_strategy_label`).
5. Emit audit events per batch.

---

## CONSTRAINTS

- **No auto-apply without `--confirm`.** Default is always dry-run.
- **P2/P3 require `--force`.** Asset class changes and label losses cannot be applied silently.
- **Rollback-safe.** Every apply can be reversed by reading `current_strategy_label` from the stage table.
- **Lineage tracked.** Both JSONB (`instruments_universe.attributes.classification_source`) and stored columns on source tables.
- **Idempotent.** Re-running apply with same run_id + severity filter is safe — already-applied rows skipped via `applied_at IS NOT NULL`.
- **No regression on unchanged rows.** If current == proposed, do nothing.
- **MV refresh once.** `mv_unified_funds` refreshed once at end of apply session, not per-row.
- **Audit per batch.** One `AuditEvent` per apply invocation, not per row (prevents flood).

---

## DELIVERABLES

### 1. Migration `0136_classification_source_columns.py`

Add lineage columns to 5 source tables. `instruments_universe` already handles it via JSONB attributes.

```python
"""Add classification_source + classification_updated_at to source tables.

Revision ID: 0136_classification_source_columns
Revises: 0135_mv_unified_funds_institutional
"""
from alembic import op
import sqlalchemy as sa

revision = "0136_classification_source_columns"
down_revision = "0135_mv_unified_funds_institutional"
branch_labels = None
depends_on = None


TABLES = [
    "sec_manager_funds",
    "sec_registered_funds",
    "sec_etfs",
    "sec_bdcs",
    "sec_money_market_funds",
    "esma_funds",
]


def upgrade() -> None:
    for table in TABLES:
        op.add_column(
            table,
            sa.Column("classification_source", sa.Text, nullable=True),
        )
        op.add_column(
            table,
            sa.Column(
                "classification_updated_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )
        # Partial index for recently reclassified rows (operator queries)
        op.create_index(
            f"idx_{table}_classification_updated",
            table,
            ["classification_updated_at"],
            postgresql_where=sa.text("classification_updated_at IS NOT NULL"),
        )


def downgrade() -> None:
    for table in TABLES:
        op.drop_index(f"idx_{table}_classification_updated", table)
        op.drop_column(table, "classification_updated_at")
        op.drop_column(table, "classification_source")
```

### 2. Service: `backend/app/domains/wealth/services/classification_family.py`

Canonical family mapping for all 51 labels across 9 families. Used by diff report and apply script.

```python
"""Strategy label family mapping.

Families group strategies that are peer-comparable. A change within a
family is a style refinement (low risk). A change across families is
an asset class change (high risk).
"""
from typing import Literal

Family = Literal[
    "equity", "fixed_income", "alts", "private",
    "hedge", "multi_asset", "convertible", "cash", "other",
]


STRATEGY_FAMILY: dict[str, Family] = {
    # ── Equity (16 labels) ────────────────────────────────────────
    "Large Blend": "equity",
    "Large Growth": "equity",
    "Large Value": "equity",
    "Mid Blend": "equity",
    "Mid Growth": "equity",
    "Mid Value": "equity",
    "Small Blend": "equity",
    "Small Growth": "equity",
    "Small Value": "equity",
    "International Equity": "equity",
    "Emerging Markets Equity": "equity",
    "Global Equity": "equity",
    "Sector Equity": "equity",
    "European Equity": "equity",
    "Asian Equity": "equity",
    "ESG/Sustainable Equity": "equity",
    # ── Fixed Income (13 labels) ──────────────────────────────────
    "Short-Term Bond": "fixed_income",
    "Intermediate-Term Bond": "fixed_income",
    "Long-Term Bond": "fixed_income",
    "High Yield Bond": "fixed_income",
    "Investment Grade Bond": "fixed_income",
    "Government Bond": "fixed_income",
    "Municipal Bond": "fixed_income",
    "International Bond": "fixed_income",
    "Inflation-Linked Bond": "fixed_income",
    "European Bond": "fixed_income",
    "Emerging Markets Debt": "fixed_income",
    "ESG/Sustainable Bond": "fixed_income",
    "Mortgage-Backed Securities": "fixed_income",
    "Asset-Backed Securities": "fixed_income",
    # ── Alternatives (4 labels) ───────────────────────────────────
    "Real Estate": "alts",
    "Infrastructure": "alts",
    "Commodities": "alts",
    "Precious Metals": "alts",
    # ── Private (4 labels) ────────────────────────────────────────
    "Private Credit": "private",
    "Private Equity": "private",
    "Venture Capital": "private",
    "Structured Credit": "private",
    # ── Hedge (7 labels) ──────────────────────────────────────────
    "Long/Short Equity": "hedge",
    "Global Macro": "hedge",
    "Multi-Strategy": "hedge",
    "Event-Driven": "hedge",
    "Volatility Arbitrage": "hedge",
    "Convertible Arbitrage": "hedge",
    "Quant/Systematic": "hedge",
    # ── Multi-Asset (3 labels) ────────────────────────────────────
    "Balanced": "multi_asset",
    "Target Date": "multi_asset",
    "Allocation": "multi_asset",
    # ── Convertible (1 label — own family, hybrid security) ──────
    "Convertible Securities": "convertible",
    # ── Cash / Other (2 labels) ───────────────────────────────────
    "Cash Equivalent": "cash",
    "Other": "other",
}


def family_of(label: str | None) -> Family | None:
    """Return family for a strategy label, or None if unknown/NULL."""
    if label is None:
        return None
    return STRATEGY_FAMILY.get(label)


def is_same_family(current: str | None, proposed: str | None) -> bool:
    """Check if two labels share a family (for style refinement detection)."""
    if current is None or proposed is None:
        return False
    return family_of(current) == family_of(proposed)


Severity = Literal[
    "unchanged",
    "safe_auto_apply",      # P0: NULL → specific
    "style_refinement",     # P1: same family
    "asset_class_change",   # P2: cross family
    "lost_class",           # P3: non-null → NULL
]


def classify_severity(
    current: str | None, proposed: str | None,
) -> Severity:
    """Classify a diff by severity for apply gating."""
    if current == proposed:
        return "unchanged"
    if current is None and proposed is not None:
        return "safe_auto_apply"
    if current is not None and proposed is None:
        return "lost_class"
    # Both non-null and differ
    if is_same_family(current, proposed):
        return "style_refinement"
    return "asset_class_change"
```

### 3. Script: `backend/scripts/strategy_diff_report.py`

Generate CSV report for manual review before apply.

```python
"""Generate classification diff report CSV.

Usage:
    python backend/scripts/strategy_diff_report.py --run-id <uuid>
    python backend/scripts/strategy_diff_report.py --run-id <uuid> --severity lost_class

Output: CSV with columns
    source_table, source_pk, fund_name, current_label, proposed_label,
    current_family, proposed_family, severity_tier, severity_label,
    classification_source, confidence, matched_pattern,
    downstream_impact_active_portfolios, downstream_impact_blocks
"""
import asyncio
import csv
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import text
from app.core.db.engine import async_session_factory as async_session
from app.domains.wealth.services.classification_family import (
    family_of, classify_severity,
)


async def fetch_stage_rows(run_id: UUID, severity_filter: str | None = None):
    """Fetch all stage rows for a run, optionally filtered by severity."""
    async with async_session() as db:
        stmt = text("""
            SELECT
                source_table, source_pk, fund_name,
                current_strategy_label, proposed_strategy_label,
                classification_source, confidence, matched_pattern
            FROM strategy_reclassification_stage
            WHERE run_id = :run_id
              AND applied_at IS NULL
            ORDER BY source_table, source_pk
        """)
        r = await db.execute(stmt, {"run_id": str(run_id)})
        rows = r.all()

    out = []
    for row in rows:
        current = row.current_strategy_label
        proposed = row.proposed_strategy_label
        severity = classify_severity(current, proposed)

        if severity_filter and severity != severity_filter:
            continue

        out.append({
            "source_table": row.source_table,
            "source_pk": row.source_pk,
            "fund_name": (row.fund_name or "")[:200],
            "current_label": current or "",
            "proposed_label": proposed or "",
            "current_family": family_of(current) or "",
            "proposed_family": family_of(proposed) or "",
            "severity_tier": {
                "unchanged": "skip",
                "safe_auto_apply": "P0",
                "style_refinement": "P1",
                "asset_class_change": "P2",
                "lost_class": "P3",
            }[severity],
            "severity_label": severity,
            "classification_source": row.classification_source or "",
            "confidence": row.confidence or "",
            "matched_pattern": row.matched_pattern or "",
        })
    return out


async def enrich_downstream_impact(rows: list[dict]) -> list[dict]:
    """For each row, count active portfolios and blocks affected.

    This is expensive — only run for P2/P3 rows to keep report time sane.
    """
    async with async_session() as db:
        for row in rows:
            # Only compute for high-risk tiers
            if row["severity_tier"] not in ("P2", "P3"):
                row["active_portfolios"] = ""
                row["allocation_blocks"] = ""
                continue

            # Count active portfolios holding this instrument
            # (Implementation depends on portfolio/holdings schema)
            pf_stmt = text("""
                SELECT COUNT(DISTINCT portfolio_id)
                FROM portfolio_holdings
                WHERE instrument_external_id = :source_pk
                  AND is_active = true
            """)
            try:
                r = await db.execute(pf_stmt, {"source_pk": row["source_pk"]})
                row["active_portfolios"] = r.scalar() or 0
            except Exception:
                row["active_portfolios"] = "?"  # Schema may differ

            # List allocation blocks for the current label
            from app.domains.wealth.vertical_engines.model_portfolio.block_mapping import (
                blocks_for_strategy_label,
            )
            row["allocation_blocks"] = ",".join(
                blocks_for_strategy_label(row["current_label"]) or []
            ) or ""

    return rows


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--severity", default=None,
        help="Filter: safe_auto_apply, style_refinement, asset_class_change, lost_class, unchanged")
    parser.add_argument("--output", default=None,
        help="Output CSV path. Defaults to reports/strategy_diff_{run_id}.csv")
    parser.add_argument("--skip-downstream", action="store_true",
        help="Skip downstream impact computation (faster)")
    args = parser.parse_args()

    run_id = UUID(args.run_id)
    output = args.output or f"reports/strategy_diff_{str(run_id)[:8]}.csv"
    Path(output).parent.mkdir(exist_ok=True, parents=True)

    rows = await fetch_stage_rows(run_id, args.severity)
    print(f"Fetched {len(rows)} stage rows")

    if not args.skip_downstream:
        print("Computing downstream impact for P2/P3 rows...")
        rows = await enrich_downstream_impact(rows)

    # Write CSV
    if not rows:
        print("No rows matching filter — skipping CSV write")
        return

    fieldnames = [
        "source_table", "source_pk", "fund_name",
        "current_label", "proposed_label",
        "current_family", "proposed_family",
        "severity_tier", "severity_label",
        "classification_source", "confidence", "matched_pattern",
        "active_portfolios", "allocation_blocks",
    ]
    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {output}")

    # Summary
    from collections import Counter
    tier_counts = Counter(r["severity_tier"] for r in rows)
    print("\nSeverity tier breakdown:")
    for tier in ("P0", "P1", "P2", "P3", "skip"):
        print(f"  {tier}: {tier_counts.get(tier, 0):,}")


if __name__ == "__main__":
    asyncio.run(main())
```

### 4. Script: `backend/scripts/apply_strategy_reclassification.py`

Apply staged labels with severity-based gating.

```python
"""Apply staged reclassification to production.

Usage:
    # Default: dry-run, no writes
    python apply_strategy_reclassification.py --run-id <uuid>

    # Apply P0 (safe_auto_apply: NULL → specific)
    python apply_strategy_reclassification.py --run-id <uuid> --severity safe --confirm

    # Apply P0 + P1 (safe + style refinement)
    python apply_strategy_reclassification.py --run-id <uuid> --severity safe,style --confirm

    # Apply P2 (asset class change) — requires --force
    python apply_strategy_reclassification.py --run-id <uuid> --severity asset_class \\
        --confirm --force

    # Apply P3 (lost_class) — requires --force + justification
    python apply_strategy_reclassification.py --run-id <uuid> --severity lost \\
        --confirm --force --justification "IC reviewed 2026-04-14: xyz"
"""
import asyncio
import getpass
import logging
import sys
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import text
from app.core.db.engine import async_session_factory as async_session
from app.domains.wealth.services.classification_family import classify_severity

logger = logging.getLogger(__name__)

SEVERITY_ALIASES = {
    "safe": "safe_auto_apply",
    "style": "style_refinement",
    "asset_class": "asset_class_change",
    "lost": "lost_class",
    "all": None,  # Means no filter
}


async def apply_batch(
    run_id: UUID,
    severities: list[str],
    *,
    dry_run: bool,
    actor: str,
    justification: str | None,
) -> dict[str, int]:
    """Apply all stage rows matching severity filter."""
    batch_id = uuid4()
    counts = {sev: 0 for sev in severities}
    counts["errors"] = 0
    counts["skipped_unchanged"] = 0
    counts["skipped_already_applied"] = 0

    async with async_session() as db:
        # Fetch candidate rows (not yet applied)
        stmt = text("""
            SELECT stage_id, source_table, source_pk, fund_name,
                   current_strategy_label, proposed_strategy_label,
                   classification_source, confidence, matched_pattern
            FROM strategy_reclassification_stage
            WHERE run_id = :run_id
              AND applied_at IS NULL
        """)
        r = await db.execute(stmt, {"run_id": str(run_id)})
        rows = r.all()

        # Map source_table to UPDATE helper
        for row in rows:
            severity = classify_severity(
                row.current_strategy_label, row.proposed_strategy_label,
            )
            if severity == "unchanged":
                counts["skipped_unchanged"] += 1
                continue
            if severity not in severities:
                continue

            if dry_run:
                counts[severity] += 1
                continue

            try:
                await _apply_one(
                    db, row, severity, batch_id, actor, justification,
                )
                counts[severity] += 1
            except Exception as e:
                logger.error("apply_failed", extra={
                    "stage_id": row.stage_id, "error": str(e),
                })
                counts["errors"] += 1

        # Refresh MV once if any applies happened
        if not dry_run and any(counts[s] > 0 for s in severities):
            await db.execute(text(
                "REFRESH MATERIALIZED VIEW CONCURRENTLY mv_unified_funds"
            ))
            logger.info("mv_unified_funds_refreshed")

        # Emit audit event per batch
        if not dry_run:
            await _emit_audit_event(
                db, run_id, batch_id, actor, severities, counts, justification,
            )

        await db.commit()

    return counts


async def _apply_one(
    db, row, severity, batch_id, actor, justification,
):
    """Apply a single stage row to production."""
    # UPDATE source table
    update_stmts = {
        "sec_manager_funds": text("""
            UPDATE sec_manager_funds
            SET strategy_label = :label,
                classification_source = :source,
                classification_updated_at = NOW()
            WHERE id::text = :pk
        """),
        "sec_registered_funds": text("""
            UPDATE sec_registered_funds
            SET strategy_label = :label,
                classification_source = :source,
                classification_updated_at = NOW()
            WHERE cik::text = :pk
        """),
        "sec_etfs": text("""
            UPDATE sec_etfs
            SET strategy_label = :label,
                classification_source = :source,
                classification_updated_at = NOW()
            WHERE series_id = :pk
        """),
        "esma_funds": text("""
            UPDATE esma_funds
            SET strategy_label = :label,
                classification_source = :source,
                classification_updated_at = NOW()
            WHERE isin = :pk
        """),
        "instruments_universe": text("""
            UPDATE instruments_universe
            SET attributes = COALESCE(attributes, '{}'::jsonb) || jsonb_build_object(
                'strategy_label', CAST(:label AS text),
                'classification_source', CAST(:source AS text),
                'classification_updated_at', CAST(:ts AS text)
            )
            WHERE instrument_id::text = :pk
        """),
    }

    if row.source_table not in update_stmts:
        raise ValueError(f"Unknown source table: {row.source_table}")

    params = {
        "label": row.proposed_strategy_label,
        "source": row.classification_source,
        "pk": row.source_pk,
    }
    if row.source_table == "instruments_universe":
        params["ts"] = datetime.now(timezone.utc).isoformat()

    await db.execute(update_stmts[row.source_table], params)

    # Mark stage row as applied
    await db.execute(text("""
        UPDATE strategy_reclassification_stage
        SET applied_at = NOW(),
            applied_by = :actor,
            applied_batch_id = :batch_id
        WHERE stage_id = :stage_id
    """), {
        "actor": actor,
        "batch_id": str(batch_id),
        "stage_id": row.stage_id,
    })


async def _emit_audit_event(
    db, run_id, batch_id, actor, severities, counts, justification,
):
    """Emit audit event for apply batch."""
    total = sum(counts[s] for s in severities if s in counts)
    if total == 0:
        return
    # Use existing write_audit_event helper
    from app.core.db.audit import write_audit_event
    await write_audit_event(
        db,
        entity_type="strategy_reclassification",
        entity_id=str(batch_id),
        action="apply_batch",
        actor=actor,
        metadata={
            "run_id": str(run_id),
            "batch_id": str(batch_id),
            "severities": severities,
            "counts": counts,
            "justification": justification,
            "applied_at": datetime.now(timezone.utc).isoformat(),
        },
    )


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--severity", required=True,
        help="Comma-separated: safe, style, asset_class, lost, all")
    parser.add_argument("--confirm", action="store_true",
        help="Actually apply (default: dry-run)")
    parser.add_argument("--force", action="store_true",
        help="Required for asset_class and lost tiers")
    parser.add_argument("--justification", default=None,
        help="Required for lost severity")
    parser.add_argument("--actor", default=None,
        help="Operator name (default: $USER)")
    args = parser.parse_args()

    # Resolve severity aliases
    requested = [s.strip() for s in args.severity.split(",")]
    if "all" in requested:
        severities = list(SEVERITY_ALIASES.values())
        severities = [s for s in severities if s is not None]
    else:
        severities = []
        for s in requested:
            resolved = SEVERITY_ALIASES.get(s)
            if resolved is None and s != "all":
                parser.error(f"Unknown severity: {s}")
            severities.append(resolved)

    # Gates
    needs_force = any(s in ("asset_class_change", "lost_class") for s in severities)
    if needs_force and not args.force:
        parser.error(
            "--force required for asset_class_change or lost_class severity"
        )
    if "lost_class" in severities and not args.justification:
        parser.error("--justification required when applying lost_class")

    actor = args.actor or getpass.getuser()
    run_id = UUID(args.run_id)

    print(f"Apply invocation:")
    print(f"  run_id: {run_id}")
    print(f"  severities: {severities}")
    print(f"  dry_run: {not args.confirm}")
    print(f"  actor: {actor}")
    if args.justification:
        print(f"  justification: {args.justification}")
    print()

    if args.confirm:
        confirm = input("Type 'APPLY' to proceed: ").strip()
        if confirm != "APPLY":
            print("Aborted.")
            return

    counts = await apply_batch(
        run_id, severities,
        dry_run=not args.confirm,
        actor=actor,
        justification=args.justification,
    )

    print("\n=== RESULT ===")
    for k, v in counts.items():
        print(f"  {k}: {v:,}")
    if not args.confirm:
        print("\n(dry-run — no changes persisted)")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(main())
```

### 5. Migration `0137` — add `applied_batch_id` to stage table

```python
"""Track which apply batch each stage row was applied under."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0137_stage_applied_batch_id"
down_revision = "0136_classification_source_columns"

def upgrade():
    op.add_column(
        "strategy_reclassification_stage",
        sa.Column(
            "applied_batch_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_stage_applied_batch",
        "strategy_reclassification_stage",
        ["applied_batch_id"],
        postgresql_where=sa.text("applied_batch_id IS NOT NULL"),
    )

def downgrade():
    op.drop_index("idx_stage_applied_batch", "strategy_reclassification_stage")
    op.drop_column("strategy_reclassification_stage", "applied_batch_id")
```

### 6. Tests

**`backend/tests/domains/wealth/services/test_classification_family.py`:**

```python
import pytest
from app.domains.wealth.services.classification_family import (
    STRATEGY_FAMILY, family_of, is_same_family, classify_severity,
)
from app.domains.wealth.services.strategy_classifier import STRATEGY_LABELS


class TestFamilyMap:
    def test_every_label_has_family(self):
        """Every label in STRATEGY_LABELS must have a family entry."""
        for label in STRATEGY_LABELS:
            assert label in STRATEGY_FAMILY, f"Missing family for: {label}"

    def test_no_stale_family_entries(self):
        """Every family entry must map to a label in STRATEGY_LABELS."""
        for label in STRATEGY_FAMILY:
            assert label in STRATEGY_LABELS, f"Stale family entry: {label}"


class TestSeverityClassification:
    @pytest.mark.parametrize("current,proposed,expected", [
        ("Large Blend", "Large Blend", "unchanged"),
        (None, None, "unchanged"),
        (None, "Large Blend", "safe_auto_apply"),
        ("Large Blend", None, "lost_class"),
        ("Large Blend", "Large Growth", "style_refinement"),  # same family
        ("Large Blend", "High Yield Bond", "asset_class_change"),  # cross family
        ("Real Estate", "Infrastructure", "style_refinement"),  # alts family
        ("Private Equity", "Real Estate", "asset_class_change"),  # private → alts
    ])
    def test_severity_classification(self, current, proposed, expected):
        assert classify_severity(current, proposed) == expected


class TestEdgeCases:
    def test_unknown_label_returns_none_family(self):
        assert family_of("Unknown Label") is None

    def test_cross_family_with_unknown(self):
        """Unknown label vs known = not same family."""
        assert not is_same_family("Unknown", "Large Blend")
```

**`backend/tests/scripts/test_apply_reclassification.py`** (integration, async):

- Fresh run_id, stage rows seeded with each severity
- Dry run returns counts, no DB changes
- `--severity safe --confirm` applies only P0 rows
- `--severity asset_class --confirm` fails without `--force`
- `--severity lost --confirm --force` fails without `--justification`
- Apply updates source table + stage table + audit event
- Re-run with same run_id/severity is no-op (already-applied rows skipped)

### 7. Documentation: `docs/reference/classification-apply-runbook.md`

```markdown
# Classification Apply Runbook

## Prerequisites
- A populated `strategy_reclassification_stage` run_id
- Migration 0136+0137 applied
- Local backup of source tables (`pg_dump` snapshot recommended for P2/P3)

## Phase 1 — Review (always)
```bash
# Full report
python backend/scripts/strategy_diff_report.py --run-id <uuid>

# High-severity only
python backend/scripts/strategy_diff_report.py --run-id <uuid> --severity asset_class_change
python backend/scripts/strategy_diff_report.py --run-id <uuid> --severity lost_class

# Inspect CSV manually before proceeding to apply
```

## Phase 2 — Apply P0 Safe (immediate, ~1,400 rows)
```bash
python backend/scripts/apply_strategy_reclassification.py \
  --run-id <uuid> --severity safe --confirm
```
Zero risk: NULL → specific label, pure gain.

## Phase 3 — Apply P1 Style Refinement (after review, ~5,000 rows)
```bash
# Review CSV first
python backend/scripts/strategy_diff_report.py --run-id <uuid> --severity style_refinement

# Apply if comfortable
python backend/scripts/apply_strategy_reclassification.py \
  --run-id <uuid> --severity style --confirm
```
Low risk: same family refinements (Large Blend → Large Growth).

## Phase 4 — Apply P2 Asset Class Change (batch review, ~13,000 rows)
```bash
# Review CSV, sort by source_table and downstream_impact
# For each source_table, review 20+ samples before applying

python backend/scripts/apply_strategy_reclassification.py \
  --run-id <uuid> --severity asset_class --confirm --force
```
Medium risk: fund moves to different family. Can affect allocation blocks.

## Phase 5 — Apply P3 Lost Class (IC approval, ~9,600 rows)
```bash
# Requires IC sign-off per source_table
python backend/scripts/apply_strategy_reclassification.py \
  --run-id <uuid> --severity lost --confirm --force \
  --justification "IC meeting 2026-04-14 approved removal for esma_funds sub-family"
```
High risk: label becomes NULL. Requires justification recorded in audit event.

## Rollback
Stage table retains `current_strategy_label`. To rollback a batch:
```sql
UPDATE sec_manager_funds f
SET strategy_label = s.current_strategy_label,
    classification_source = 'rollback',
    classification_updated_at = NOW()
FROM strategy_reclassification_stage s
WHERE s.applied_batch_id = :batch_id
  AND s.source_table = 'sec_manager_funds'
  AND f.id::text = s.source_pk;

-- Repeat per source_table
-- Then:
UPDATE strategy_reclassification_stage
SET applied_at = NULL, applied_by = NULL, applied_batch_id = NULL
WHERE applied_batch_id = :batch_id;

REFRESH MATERIALIZED VIEW CONCURRENTLY mv_unified_funds;
```
```

---

## VERIFICATION

1. `make lint` + `make typecheck` pass.
2. `make test` passes (new family map + severity + apply tests).
3. Migrations 0136, 0137 apply cleanly.
4. Diff report CSV generates with expected ~51 distinct `proposed_family` values.
5. Dry-run apply with `--severity safe` shows ~1,400 rows, zero DB changes.
6. Actual apply with `--severity safe --confirm` updates ~1,400 rows in source tables + stage table, emits 1 audit event, refreshes mv_unified_funds.
7. Re-running same apply is no-op (idempotency via `applied_at IS NOT NULL`).
8. Apply `--severity asset_class` without `--force` errors out cleanly.
9. Apply `--severity lost --force` without `--justification` errors out cleanly.
10. Random spot-check: pick 5 applied rows, verify source_table.strategy_label matches proposed_strategy_label in stage.

---

## EXPECTED POST-APPLY STATE

After Phase 2 (safe only):
- sec_etfs: +542 newly classified (NULL → specific)
- instruments_universe: +858 newly classified

After all phases applied:
- Production strategy_label aligned with Round 2 classifier output for ~29,000 rows
- 55,000+ rows unchanged (already correct)
- Every applied row has `classification_source` lineage
- Stage table remains as historical record (applied_at timestamps preserved)

---

## ANTI-PATTERNS

- Do NOT apply P2/P3 without reviewing CSV samples per source_table.
- Do NOT skip `--force` / `--justification` gates via code changes.
- Do NOT apply all severities in one invocation. Phase them.
- Do NOT run MV refresh per-row — only once at end of batch.
- Do NOT modify staging table to "clean up" — it's historical audit.
- Do NOT auto-apply from a cron or scheduled job. Human must invoke.

---

## OUT OF SCOPE

- **Phase 4 (N-PORT holdings classifier)** — replaces Round 3 as canonical fix for ESMA residuals. Separate sprint after Construction Engine Phase A.
- **Round 3 patches** — explicitly rejected (diminishing returns, linguistic over-fit).
- **UI for diff review** — CSV → spreadsheet is sufficient for now. Could build web dashboard later.
- **Automatic conflict resolution** — if two run_ids propose different labels for the same fund, operator picks manually.
- **Audit event per-row** — too noisy. Per-batch is sufficient.

---

## Post-merge operator sequence

1. `make migrate` (applies 0136 + 0137)
2. `make test` (all green)
3. `pg_dump` snapshot of source tables (insurance)
4. Run diff report for run_id `b5623a5b-9f2d-4df7-b02f-0726a9703ea8`
5. Apply P0 safe
6. Inspect spot samples, verify production UPDATE fired
7. Review P1 style_refinement CSV, apply
8. Schedule P2/P3 review sessions with domain expert
9. Document applied batch_ids in `docs/reference/classification-apply-runbook.md` for audit trail
