"""PR-A23 Section D — fix known-wrong ``strategy_label`` values on
``instruments_universe`` for the ~30 most-liquid US ETFs.

Pure data migration — no schema changes. Corrects upstream ingestion
defects surfaced by the PR-A23 audit:

* ``AGG`` / ``BND``: labelled "Government Bond" — should be "Intermediate
  Core Bond".
* ``EFA`` / ``VEA`` / ``IEFA``: labelled "Government Bond" or similar —
  should be "Foreign Large Blend".
* ``VTEB`` / ``MUB``: labelled as aggregate — should be "Muni National
  Interm" (classifier downstream still surfaces these for operator
  review because ``fi_us_aggregate_muni`` is not a registered block).
* plus the rest of the PR-A23 canonical reference (SPY, QQQ, GLD, …).

Captures a backup snapshot of pre-migration ``strategy_label`` values
into ``pr_a23_strategy_label_backup`` so ``downgrade`` can restore
them exactly.

Idempotent — each UPDATE has ``IS DISTINCT FROM`` guard so re-running
the upgrade is a no-op.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0151_fix_known_strategy_labels"
down_revision = "0150_winner_signal_block_coverage"
branch_labels = None
depends_on = None


# Duplicated from ``backend/scripts/_pr_a23_canonical_reference.py`` so
# the migration is a self-contained time-capsule (standard Alembic
# practice — never import application code from migrations). Keep in
# sync via the audit script's re-run check.
_CANONICAL_LABELS: dict[str, str] = {
    # Equity — US Blend
    "SPY": "Large Blend",
    "IVV": "Large Blend",
    "VOO": "Large Blend",
    "VTI": "Large Blend",
    # Equity — US Growth
    "QQQ": "Large Growth",
    "VUG": "Large Growth",
    "IWF": "Large Growth",
    # Equity — US Value
    "VTV": "Large Value",
    "IWD": "Large Value",
    # Equity — US Small
    "IWM": "Small Blend",
    "VB": "Small Blend",
    # Equity — International Developed
    "EFA": "Foreign Large Blend",
    "VEA": "Foreign Large Blend",
    "IEFA": "Foreign Large Blend",
    # Equity — Emerging Markets
    "EEM": "Diversified Emerging Mkts",
    "VWO": "Diversified Emerging Mkts",
    "IEMG": "Diversified Emerging Mkts",
    # Fixed Income — Aggregate
    "AGG": "Intermediate Core Bond",
    "BND": "Intermediate Core Bond",
    # Fixed Income — Treasury / Government
    "IEF": "Intermediate Government",
    "TLT": "Long Government",
    "SHY": "Short Government",
    "GOVT": "Intermediate Government",
    # Fixed Income — Muni
    "VTEB": "Muni National Interm",
    "MUB": "Muni National Interm",
    # Fixed Income — TIPS
    "TIP": "Inflation-Protected Bond",
    "SCHP": "Inflation-Protected Bond",
    # Fixed Income — High Yield
    "HYG": "High Yield Bond",
    "JNK": "High Yield Bond",
    # Fixed Income — IG Corporate
    "LQD": "Corporate Bond",
    # Alternatives — Gold
    "GLD": "Precious Metals",
    "IAU": "Precious Metals",
    # Alternatives — Broad Commodities
    "DBC": "Commodities Broad Basket",
    "GSG": "Commodities Broad Basket",
    # Alternatives — Real Estate
    "VNQ": "Real Estate",
}


_BACKUP_TABLE = "pr_a23_strategy_label_backup"


def upgrade() -> None:
    conn = op.get_bind()

    # ── Step 1 — create backup table ──────────────────────────────
    # Idempotent: if rerun, preserve the original snapshot rather than
    # recapturing post-update state.
    conn.execute(
        sa.text(
            f"""
            CREATE TABLE IF NOT EXISTS {_BACKUP_TABLE} (
                ticker TEXT NOT NULL,
                instrument_id UUID NOT NULL,
                prior_strategy_label TEXT,
                captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (ticker, instrument_id)
            )
            """
        )
    )

    # Capture pre-update state for every row we're about to touch. The
    # ON CONFLICT DO NOTHING preserves the original snapshot across
    # reruns — we only ever back up the pristine value.
    conn.execute(
        sa.text(
            f"""
            INSERT INTO {_BACKUP_TABLE}
                (ticker, instrument_id, prior_strategy_label)
            SELECT iu.ticker,
                   iu.instrument_id,
                   iu.attributes->>'strategy_label'
              FROM instruments_universe iu
             WHERE iu.ticker = ANY(:tickers)
             ON CONFLICT (ticker, instrument_id) DO NOTHING
            """
        ),
        {"tickers": sorted(_CANONICAL_LABELS.keys())},
    )

    # ── Step 2 — apply per-ticker strategy_label corrections ─────
    for ticker, canonical_label in _CANONICAL_LABELS.items():
        conn.execute(
            sa.text(
                """
                UPDATE instruments_universe
                   SET attributes = jsonb_set(
                       COALESCE(attributes, '{}'::jsonb),
                       '{strategy_label}',
                       to_jsonb(:label::text),
                       true
                   )
                 WHERE ticker = :ticker
                   AND COALESCE(attributes->>'strategy_label', '')
                       IS DISTINCT FROM :label
                """
            ),
            {"ticker": ticker, "label": canonical_label},
        )


def downgrade() -> None:
    conn = op.get_bind()

    # Restore every pre-migration strategy_label from the backup. If the
    # prior value was NULL, the jsonb key is removed entirely (matches
    # the expected "label was never set" state).
    conn.execute(
        sa.text(
            f"""
            UPDATE instruments_universe iu
               SET attributes = CASE
                   WHEN b.prior_strategy_label IS NULL
                        THEN COALESCE(iu.attributes, '{{}}'::jsonb)
                             - 'strategy_label'
                   ELSE jsonb_set(
                       COALESCE(iu.attributes, '{{}}'::jsonb),
                       '{{strategy_label}}',
                       to_jsonb(b.prior_strategy_label::text),
                       true
                   )
               END
              FROM {_BACKUP_TABLE} b
             WHERE iu.instrument_id = b.instrument_id
               AND iu.ticker = b.ticker
            """
        )
    )

    conn.execute(sa.text(f"DROP TABLE IF EXISTS {_BACKUP_TABLE}"))
