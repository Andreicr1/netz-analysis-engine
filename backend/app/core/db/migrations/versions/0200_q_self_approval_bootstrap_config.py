"""PR-OPS-2 — bootstrap-only self-approval policy seed.

Per `docs/plans/2026-04-30-builder-workspace-redesign-final.md` §1.1 +
§9 (PR-OPS-2), the wealth model-portfolio lifecycle requires the
canonical/bootstrap dev org to operate as a single-user shop while
every external tenant defaults to the conservative posture
(``allow_self_approval=False``).

This migration:

1. Expands the ``ck_defaults_config_type`` and ``ck_overrides_config_type``
   CHECK constraints to allow ``'approval_policy'`` as a config_type
   value. The (vertical='wealth', config_type='approval_policy') domain
   was already declared in ``app.core.config.registry`` but no migration
   had widened the CHECK enum to accept it as a stored value, which
   would block the override INSERT below.

2. Inserts the bootstrap org override granting ``allow_self_approval=true``
   for org id ``403d8392-ebfa-5890-b740-45da49c556eb``. The same UUID is
   used by 0160 to seed canonical-org instrument approvals — single
   bootstrap org, multiple seeds.

3. Does NOT insert a default row in ``vertical_config_defaults``. The
   ``approval_policy`` domain is registered as ``required=False``, so
   ``ConfigService.get`` returns a typed-miss (``MISSING_OPTIONAL``)
   when no default exists, and ``_resolve_approval_policy`` already
   degrades cleanly to the conservative ``ApprovalPolicy()`` default
   (``allow_self_approval=False``, ``require_construction_for_approve=
   True``). Keeping the default row absent is the institutional posture:
   any new tenant must opt in via a per-org override, not inherit
   self-approval globally.

Idempotent — uses ``ON CONFLICT (organization_id, vertical, config_type)
DO NOTHING`` against the ``uq_overrides_org_vertical_type`` unique key.

Revision ID: 0200_q_self_approval_bootstrap_config
Revises: 0199_q165_consolidate_aggressive_into_growth
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0200_q_self_approval_bootstrap_config"
down_revision = "0199_q165_consolidate_aggressive_into_growth"
branch_labels = None
depends_on = None

# Bootstrap / canonical dev org. Same UUID seeded by 0160.
BOOTSTRAP_ORG_ID = "403d8392-ebfa-5890-b740-45da49c556eb"

# CHECK constraint values — keep in sync with `app.core.config.registry`.
# Defaults CHECK was last updated in 0128 (added taa_bands).
# Overrides CHECK was last updated in 0007 (added governance_policy).
# Both lists below include every value that has been allowed historically
# in the respective constraint, plus 'approval_policy'.
_DEFAULTS_CONFIG_TYPES = (
    "'calibration', 'scoring', 'blocks', 'chapters', "
    "'portfolio_profiles', 'prompts', 'model_routing', 'tone', "
    "'evaluation', 'macro_intelligence', 'governance_policy', "
    "'branding', 'screening_layer1', 'screening_layer2', "
    "'screening_layer3', 'taa_bands', 'approval_policy'"
)
_DEFAULTS_CONFIG_TYPES_PRIOR = (
    "'calibration', 'scoring', 'blocks', 'chapters', "
    "'portfolio_profiles', 'prompts', 'model_routing', 'tone', "
    "'evaluation', 'macro_intelligence', 'governance_policy', "
    "'branding', 'screening_layer1', 'screening_layer2', "
    "'screening_layer3', 'taa_bands'"
)
_OVERRIDES_CONFIG_TYPES = (
    "'calibration', 'scoring', 'blocks', 'chapters', "
    "'portfolio_profiles', 'prompts', 'model_routing', 'tone', "
    "'evaluation', 'macro_intelligence', 'governance_policy', "
    "'approval_policy'"
)
_OVERRIDES_CONFIG_TYPES_PRIOR = (
    "'calibration', 'scoring', 'blocks', 'chapters', "
    "'portfolio_profiles', 'prompts', 'model_routing', 'tone', "
    "'evaluation', 'macro_intelligence', 'governance_policy'"
)

# Bootstrap-only override payload. Field shape mirrors the dataclass in
# vertical_engines/wealth/model_portfolio/state_machine.py::ApprovalPolicy.
_BOOTSTRAP_APPROVAL_POLICY: dict = {
    "allow_self_approval": True,
    # Keep the institutional construction-gate: even bootstrap requires a
    # passing construction run before approve is offered. The single-user
    # shop loosens *who* may approve, not *what* must be validated first.
    "require_construction_for_approve": True,
}


def upgrade() -> None:
    # ── Widen CHECK constraints to allow 'approval_policy' ──────────
    op.execute("ALTER TABLE vertical_config_defaults DROP CONSTRAINT IF EXISTS ck_defaults_config_type")
    op.execute(
        f"""
        ALTER TABLE vertical_config_defaults
        ADD CONSTRAINT ck_defaults_config_type
        CHECK (config_type IN ({_DEFAULTS_CONFIG_TYPES}))
        """,
    )

    op.execute("ALTER TABLE vertical_config_overrides DROP CONSTRAINT IF EXISTS ck_overrides_config_type")
    op.execute(
        f"""
        ALTER TABLE vertical_config_overrides
        ADD CONSTRAINT ck_overrides_config_type
        CHECK (config_type IN ({_OVERRIDES_CONFIG_TYPES}))
        """,
    )

    # ── Seed bootstrap-only override ────────────────────────────────
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            INSERT INTO vertical_config_overrides
                (id, organization_id, vertical, config_type, config, created_by)
            VALUES (
                gen_random_uuid(),
                :org_id,
                :vertical,
                :config_type,
                :config,
                'migration:0200_self_approval_bootstrap'
            )
            ON CONFLICT (organization_id, vertical, config_type) DO NOTHING
            """,
        ),
        {
            "org_id": BOOTSTRAP_ORG_ID,
            "vertical": "wealth",
            "config_type": "approval_policy",
            "config": json.dumps(_BOOTSTRAP_APPROVAL_POLICY),
        },
    )


def downgrade() -> None:
    # 1. Remove the bootstrap override BEFORE narrowing the CHECK.
    op.execute(
        f"""
        DELETE FROM vertical_config_overrides
         WHERE organization_id = '{BOOTSTRAP_ORG_ID}'::uuid
           AND vertical = 'wealth'
           AND config_type = 'approval_policy'
        """,
    )

    # Defensive: in case anyone else added approval_policy rows on the
    # downgrade path, drop them so the CHECK narrowing succeeds.
    op.execute(
        """
        DELETE FROM vertical_config_overrides WHERE config_type = 'approval_policy';
        DELETE FROM vertical_config_defaults  WHERE config_type = 'approval_policy';
        """,
    )

    # 2. Restore prior CHECK constraints (without 'approval_policy').
    op.execute("ALTER TABLE vertical_config_defaults DROP CONSTRAINT IF EXISTS ck_defaults_config_type")
    op.execute(
        f"""
        ALTER TABLE vertical_config_defaults
        ADD CONSTRAINT ck_defaults_config_type
        CHECK (config_type IN ({_DEFAULTS_CONFIG_TYPES_PRIOR}))
        """,
    )

    op.execute("ALTER TABLE vertical_config_overrides DROP CONSTRAINT IF EXISTS ck_overrides_config_type")
    op.execute(
        f"""
        ALTER TABLE vertical_config_overrides
        ADD CONSTRAINT ck_overrides_config_type
        CHECK (config_type IN ({_OVERRIDES_CONFIG_TYPES_PRIOR}))
        """,
    )
