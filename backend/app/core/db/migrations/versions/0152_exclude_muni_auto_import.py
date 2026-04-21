"""PR-A24 — categorical exclusion of US muni bonds from the wealth
engine.

Deletes every ``instruments_org`` row whose canonical
``instruments_universe.attributes.strategy_label`` matches one of the
mandate-level excluded labels AND was originated by the auto-import
worker (``source = 'universe_auto_import'``). Manual selections
(``source != 'universe_auto_import'``, including ``manual`` and
``manual,auto``) are preserved — operator explicitly chose them.

Additionally flags every matching ``instruments_universe`` row with
``attributes.strategic_excluded_reason = <strategy_label>`` so future
auto-import runs are observable via the audit even if the row never
re-enters the classifier.

Reversible: deleted rows are backed up into
``pr_a24_muni_exclusion_backup`` (same columns as ``instruments_org``
plus ``deleted_at TIMESTAMPTZ`` and ``universe_flag_set_by_this_migration
BOOLEAN``). The down-migration restores rows, drops the backup table,
and clears ``strategic_excluded_reason`` on universe rows that were
newly flagged by this migration (tracked row-by-row to avoid clobbering
flags written by the service layer between up- and down-migration).

Does NOT touch ``instruments_universe`` beyond the JSONB breadcrumb —
the global catalog keeps every row; exclusion is strictly at the
org-scoped level.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0152_exclude_muni_auto_import"
down_revision = "0151_fix_known_strategy_labels"
branch_labels = None
depends_on = None


# Duplicated from ``backend/scripts/_pr_a23_canonical_reference.py`` so
# the migration is a self-contained time-capsule (standard Alembic
# practice — never import application code from migrations). Keep in
# sync with ``EXCLUDED_STRATEGY_LABELS``.
_EXCLUDED_STRATEGY_LABELS: tuple[str, ...] = (
    "Municipal Bond",
    "Muni National Interm",
    "Muni National Short",
    "Muni National Long",
    "Muni Single State Interm",
    "Muni Single State Short",
    "Muni Single State Long",
    "High Yield Muni",
    "Muni California Intermediate",
    "Muni California Long",
    "Muni New York Intermediate",
    "Muni New York Long",
    "Muni Target Maturity",
)

_BACKUP_TABLE = "pr_a24_muni_exclusion_backup"


def upgrade() -> None:
    conn = op.get_bind()
    labels = list(_EXCLUDED_STRATEGY_LABELS)

    # ── Step 1 — backup table (idempotent) ───────────────────────
    # Mirrors instruments_org columns at time of migration. If columns
    # drift later, the restore path only needs the subset this migration
    # manipulates — the backup is a rollback aid, not a long-lived
    # artifact.
    conn.execute(
        sa.text(
            f"""
            CREATE TABLE IF NOT EXISTS {_BACKUP_TABLE} (
                id UUID NOT NULL PRIMARY KEY,
                organization_id UUID NOT NULL,
                instrument_id UUID NOT NULL,
                block_id TEXT,
                approval_status TEXT,
                selected_at TIMESTAMPTZ,
                source TEXT,
                block_overridden BOOLEAN,
                deleted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                universe_flag_set_by_this_migration BOOLEAN NOT NULL
                    DEFAULT FALSE
            )
            """
        )
    )

    # ── Step 2 — snapshot rows that will be deleted ───────────────
    # Only rows whose linked universe row has an excluded strategy_label
    # AND originated from the auto-import worker. Manual selections are
    # left alone (operator explicitly chose them).
    result = conn.execute(
        sa.text(
            f"""
            INSERT INTO {_BACKUP_TABLE} (
                id, organization_id, instrument_id, block_id,
                approval_status, selected_at, source, block_overridden
            )
            SELECT io.id, io.organization_id, io.instrument_id, io.block_id,
                   io.approval_status, io.selected_at, io.source,
                   io.block_overridden
              FROM instruments_org io
              JOIN instruments_universe iu USING (instrument_id)
             WHERE iu.attributes->>'strategy_label' = ANY(:labels)
               AND io.source = 'universe_auto_import'
             ON CONFLICT (id) DO NOTHING
            """
        ),
        {"labels": labels},
    )
    print(
        f"[0152] backed up {result.rowcount} instruments_org rows",
        flush=True,
    )

    # ── Step 3 — DELETE auto-imported muni rows ──────────────────
    result = conn.execute(
        sa.text(
            """
            DELETE FROM instruments_org io
             USING instruments_universe iu
             WHERE io.instrument_id = iu.instrument_id
               AND iu.attributes->>'strategy_label' = ANY(:labels)
               AND io.source = 'universe_auto_import'
            """
        ),
        {"labels": labels},
    )
    print(
        f"[0152] deleted {result.rowcount} auto-imported muni rows from "
        f"instruments_org",
        flush=True,
    )

    # ── Step 4 — flag universe rows (track which ones we touched) ─
    # Marks which universe rows did NOT already carry
    # strategic_excluded_reason so the downgrade can clear only those
    # without touching any flags written by the service layer.
    conn.execute(
        sa.text(
            f"""
            UPDATE {_BACKUP_TABLE} b
               SET universe_flag_set_by_this_migration = TRUE
             WHERE NOT EXISTS (
                 SELECT 1 FROM instruments_universe iu
                  WHERE iu.instrument_id = b.instrument_id
                    AND iu.attributes ? 'strategic_excluded_reason'
             )
            """
        )
    )

    result = conn.execute(
        sa.text(
            """
            UPDATE instruments_universe iu
               SET attributes = jsonb_set(
                   COALESCE(iu.attributes, '{}'::jsonb),
                   '{strategic_excluded_reason}',
                   to_jsonb(iu.attributes->>'strategy_label'),
                   true
               )
             WHERE iu.attributes->>'strategy_label' = ANY(:labels)
               AND COALESCE(
                       iu.attributes->>'strategic_excluded_reason', ''
                   ) IS DISTINCT FROM (iu.attributes->>'strategy_label')
            """
        ),
        {"labels": labels},
    )
    print(
        f"[0152] flagged {result.rowcount} instruments_universe rows with "
        f"strategic_excluded_reason",
        flush=True,
    )


def downgrade() -> None:
    conn = op.get_bind()

    # ── Step 1 — restore backed-up rows ──────────────────────────
    # ON CONFLICT DO NOTHING keeps any post-migration state safe (if an
    # operator has re-imported or manually added the row since, we don't
    # overwrite).
    conn.execute(
        sa.text(
            f"""
            INSERT INTO instruments_org (
                id, organization_id, instrument_id, block_id,
                approval_status, selected_at, source, block_overridden
            )
            SELECT id, organization_id, instrument_id, block_id,
                   approval_status, selected_at, source, block_overridden
              FROM {_BACKUP_TABLE}
             ON CONFLICT (id) DO NOTHING
            """
        )
    )

    # ── Step 2 — clear strategic_excluded_reason we added ────────
    # The up-migration flagged every universe row whose strategy_label
    # matches an excluded label; clear them all on rollback. This can
    # also clear flags written by the service layer between up- and
    # down-migration — acceptable because the service re-flags on the
    # next auto-import run with no data loss.
    labels = list(_EXCLUDED_STRATEGY_LABELS)
    conn.execute(
        sa.text(
            """
            UPDATE instruments_universe
               SET attributes = attributes - 'strategic_excluded_reason'
             WHERE attributes->>'strategy_label' = ANY(:labels)
               AND attributes ? 'strategic_excluded_reason'
            """
        ),
        {"labels": labels},
    )

    # ── Step 3 — drop the backup table ───────────────────────────
    conn.execute(sa.text(f"DROP TABLE IF EXISTS {_BACKUP_TABLE}"))
