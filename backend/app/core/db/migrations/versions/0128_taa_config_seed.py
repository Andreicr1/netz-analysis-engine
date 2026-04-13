"""Seed TAA regime band configuration in vertical_config_defaults.

Provides default regime-to-allocation band mapping used by the TAA
band service (taa_band_service.py) and the construction pipeline.

Centers sum to 1.0 per regime (validated at seed time).
Half widths define the regime band around each center.
Transition config controls EMA smoothing and daily shift caps.

Revision ID: 0128_taa_config_seed
Revises: 0127_taa_regime_state
Create Date: 2026-04-12
"""
from __future__ import annotations

import json

from alembic import op
from sqlalchemy import text

revision = "0128_taa_config_seed"
down_revision = "0127_taa_regime_state"
branch_labels = None
depends_on = None

_TAA_BANDS_CONFIG = {
    "regime_bands": {
        "RISK_ON": {
            "equity":       {"center": 0.52, "half_width": 0.08},
            "fixed_income": {"center": 0.30, "half_width": 0.06},
            "alternatives": {"center": 0.12, "half_width": 0.04},
            "cash":         {"center": 0.06, "half_width": 0.03},
        },
        "RISK_OFF": {
            "equity":       {"center": 0.38, "half_width": 0.08},
            "fixed_income": {"center": 0.36, "half_width": 0.06},
            "alternatives": {"center": 0.13, "half_width": 0.04},
            "cash":         {"center": 0.13, "half_width": 0.05},
        },
        "INFLATION": {
            "equity":       {"center": 0.42, "half_width": 0.08},
            "fixed_income": {"center": 0.25, "half_width": 0.06},
            "alternatives": {"center": 0.22, "half_width": 0.06},
            "cash":         {"center": 0.11, "half_width": 0.04},
        },
        "CRISIS": {
            "equity":       {"center": 0.25, "half_width": 0.06},
            "fixed_income": {"center": 0.35, "half_width": 0.06},
            "alternatives": {"center": 0.15, "half_width": 0.05},
            "cash":         {"center": 0.25, "half_width": 0.08},
        },
    },
    "transition": {
        "ema_halflife_days": 5,
        "min_confidence_to_act": 0.60,
        "max_daily_shift_pct": 0.03,
    },
    "ips_override_priority": True,
}

# Validate center sums at migration definition time
for _regime, _bands in _TAA_BANDS_CONFIG["regime_bands"].items():
    _center_sum = sum(b["center"] for b in _bands.values())
    assert abs(_center_sum - 1.0) < 0.01, f"{_regime} centers sum to {_center_sum}, expected 1.0"


def upgrade() -> None:
    op.execute(
        text("""
            INSERT INTO vertical_config_defaults
                (id, vertical, config_type, config, description, created_by)
            VALUES
                (gen_random_uuid(), 'liquid_funds', 'taa_bands', :config,
                 'Regime-to-allocation band mapping for TAA system', 'migration:0128')
            ON CONFLICT (vertical, config_type) DO NOTHING
        """),
        {"config": json.dumps(_TAA_BANDS_CONFIG)},
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM vertical_config_defaults WHERE config_type = 'taa_bands'"
    )
