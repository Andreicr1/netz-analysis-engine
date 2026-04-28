"""Rename screener criterion keys from plural to singular to match data schema.

Layer 1: allowed_domiciles → allowed_domicile, allowed_structures → allowed_structure,
         allowed_exchanges → allowed_exchange.
Layer 2: allowed_strategies → allowed_strategy_label (data key is strategy_label).

Root cause: layer_evaluator.py:174 strips "allowed_" prefix and looks up the
remaining string as an exact key in JSONB attributes. Config used plural forms
("domiciles", "structures") but data stores singular ("domicile", "structure").
Result: 100% Layer 1 reject in production (6851/6851 instruments failed).

Idempotent: uses jsonb_path_exists guard — re-running is safe.

Revision ID: 0186_screener_criterion_key_singular
Revises: 0185_esma_ucits_structure_backfill
Create Date: 2026-04-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0186_screener_criterion_key_singular"
down_revision: str | None = "0185_esma_ucits_structure_backfill"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ── Key renames per config_type ──────────────────────────────────────

_L1_RENAMES = {
    # (parent_path, old_key, new_key)
    ("fund", "allowed_domiciles", "allowed_domicile"),
    ("fund", "allowed_structures", "allowed_structure"),
    ("equity", "allowed_exchanges", "allowed_exchange"),
}

_L2_RENAMES = {
    # ALTERNATIVES block criteria
    ("blocks", "ALTERNATIVES", "criteria", "allowed_strategies", "allowed_strategy_label"),
}


def _rename_jsonb_key(
    table: str,
    config_type: str,
    path_parts: tuple[str, ...],
    old_key: str,
    new_key: str,
    extra_where: str = "",
) -> str:
    """Build idempotent SQL to rename a JSONB key at an arbitrary depth."""
    # Build the jsonb_path_exists guard for the OLD key
    jp_parts = ".".join(path_parts) + f".{old_key}" if path_parts else old_key
    jsonpath = f"$.{jp_parts}"

    # Build nested jsonb_set to add new key then remove old key
    # Step 1: extract value at old path
    old_accessor = "".join(f"->'{p}'" for p in path_parts) + f"->'{old_key}'"
    # Step 2: set new key at same parent path
    new_path = "'{" + ",".join(path_parts) + f",{new_key}" + "}'"
    # Step 3: remove old key via #- operator
    remove_path = "'{" + ",".join(path_parts) + f",{old_key}" + "}'"

    where_clause = f"config_type = '{config_type}'"
    if extra_where:
        where_clause += f" AND {extra_where}"

    return f"""
UPDATE {table}
SET config = (config #- {remove_path})::jsonb || jsonb_build_object()
WHERE {where_clause}
  AND jsonb_path_exists(config, '{jsonpath}');

UPDATE {table}
SET config = jsonb_set(
    config,
    {new_path},
    (SELECT config{old_accessor} FROM {table} t2 WHERE t2.id = {table}.id)
)
WHERE {where_clause}
  AND jsonb_path_exists(config, '{jsonpath}');
"""


def upgrade() -> None:
    bind = op.get_bind()

    # ── Layer 1: vertical_config_defaults ────────────────────────────
    for parent, old_key, new_key in _L1_RENAMES:
        # Add new key with value from old key, then remove old key
        # Idempotent: only runs if old key exists
        bind.execute(sa.text(f"""
            UPDATE vertical_config_defaults
            SET config = jsonb_set(
                config #- '{{{parent},{old_key}}}',
                '{{{parent},{new_key}}}',
                config->'{parent}'->'{old_key}'
            )
            WHERE vertical = 'liquid_funds'
              AND config_type = 'screening_layer1'
              AND jsonb_path_exists(config, '$.{parent}.{old_key}')
        """))

    # ── Layer 1: vertical_config_overrides ───────────────────────────
    for parent, old_key, new_key in _L1_RENAMES:
        bind.execute(sa.text(f"""
            UPDATE vertical_config_overrides
            SET config = jsonb_set(
                config #- '{{{parent},{old_key}}}',
                '{{{parent},{new_key}}}',
                config->'{parent}'->'{old_key}'
            )
            WHERE config_type = 'screening_layer1'
              AND jsonb_path_exists(config, '$.{parent}.{old_key}')
        """))

    # ── Layer 2: allowed_strategies → allowed_strategy_label ─────────
    for table in ("vertical_config_defaults", "vertical_config_overrides"):
        bind.execute(sa.text(f"""
            UPDATE {table}
            SET config = jsonb_set(
                config #- '{{blocks,ALTERNATIVES,criteria,allowed_strategies}}',
                '{{blocks,ALTERNATIVES,criteria,allowed_strategy_label}}',
                config->'blocks'->'ALTERNATIVES'->'criteria'->'allowed_strategies'
            )
            WHERE config_type = 'screening_layer2'
              AND jsonb_path_exists(config, '$.blocks.ALTERNATIVES.criteria.allowed_strategies')
        """))


def downgrade() -> None:
    bind = op.get_bind()

    # ── Layer 1: reverse renames ─────────────────────────────────────
    for parent, old_key, new_key in _L1_RENAMES:
        # Reverse: new_key → old_key
        bind.execute(sa.text(f"""
            UPDATE vertical_config_defaults
            SET config = jsonb_set(
                config #- '{{{parent},{new_key}}}',
                '{{{parent},{old_key}}}',
                config->'{parent}'->'{new_key}'
            )
            WHERE vertical = 'liquid_funds'
              AND config_type = 'screening_layer1'
              AND jsonb_path_exists(config, '$.{parent}.{new_key}')
        """))

        bind.execute(sa.text(f"""
            UPDATE vertical_config_overrides
            SET config = jsonb_set(
                config #- '{{{parent},{new_key}}}',
                '{{{parent},{old_key}}}',
                config->'{parent}'->'{new_key}'
            )
            WHERE config_type = 'screening_layer1'
              AND jsonb_path_exists(config, '$.{parent}.{new_key}')
        """))

    # ── Layer 2: reverse rename ──────────────────────────────────────
    for table in ("vertical_config_defaults", "vertical_config_overrides"):
        bind.execute(sa.text(f"""
            UPDATE {table}
            SET config = jsonb_set(
                config #- '{{blocks,ALTERNATIVES,criteria,allowed_strategy_label}}',
                '{{blocks,ALTERNATIVES,criteria,allowed_strategies}}',
                config->'blocks'->'ALTERNATIVES'->'criteria'->'allowed_strategy_label'
            )
            WHERE config_type = 'screening_layer2'
              AND jsonb_path_exists(config, '$.blocks.ALTERNATIVES.criteria.allowed_strategy_label')
        """))
