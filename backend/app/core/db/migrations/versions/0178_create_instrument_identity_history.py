"""Create instrument_identity_history table + AFTER UPDATE trigger.

PR-Q11 Phase 1.2 — Append-only SCD history for instrument identity changes.

History records every field-level change with old/new values, source,
and validity range. The trigger fires AFTER UPDATE on instrument_identity
and inserts one history row per modified field.

instrument_id has NO FK intentionally — history must survive if the
current row or universe row is deleted.

Revision ID: 0178_create_instrument_identity_history
Revises: 0177_create_instrument_identity
Create Date: 2026-04-26
"""
from alembic import op

revision = "0178_create_instrument_identity_history"
down_revision = "0177_create_instrument_identity"
branch_labels = None
depends_on = None

# Fields tracked by the history trigger
_TRACKED_FIELDS = [
    "cik_padded",
    "cik_unpadded",
    "sec_series_id",
    "sec_class_id",
    "sec_crd",
    "sec_private_fund_id",
    "cusip_8",
    "cusip_9",
    "isin",
    "sedol",
    "figi",
    "ticker",
    "ticker_exchange",
    "mic",
    "lei",
    "esma_manager_id",
    "resolution_status",
]


def upgrade() -> None:
    # --- HISTORY TABLE ---
    op.execute("""
        CREATE TABLE instrument_identity_history (
            history_id          BIGSERIAL PRIMARY KEY,
            instrument_id       UUID NOT NULL,
            field_name          VARCHAR(50) NOT NULL,
            old_value           TEXT,
            new_value           TEXT,
            source              VARCHAR(50) NOT NULL,
            observed_at         TIMESTAMPTZ NOT NULL,
            valid_from          TIMESTAMPTZ NOT NULL,
            valid_to            TIMESTAMPTZ,
            confidence_status   VARCHAR(20) NOT NULL,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # --- INDEXES ---
    op.execute("""
        CREATE INDEX ix_identity_history_instrument
            ON instrument_identity_history(instrument_id, valid_from DESC)
    """)
    op.execute("""
        CREATE INDEX ix_identity_history_field
            ON instrument_identity_history(field_name, observed_at DESC)
    """)
    op.execute("""
        CREATE INDEX ix_identity_history_current
            ON instrument_identity_history(instrument_id, field_name)
            WHERE valid_to IS NULL
    """)

    # --- TRIGGER FUNCTION ---
    # Build per-field IF blocks for the trigger
    field_checks = []
    for field in _TRACKED_FIELDS:
        field_checks.append(f"""
        IF OLD.{field} IS DISTINCT FROM NEW.{field} THEN
            -- Close previous current row for this field
            UPDATE instrument_identity_history
            SET valid_to = NOW()
            WHERE instrument_id = NEW.instrument_id
              AND field_name = '{field}'
              AND valid_to IS NULL;

            -- Insert new history row
            INSERT INTO instrument_identity_history (
                instrument_id, field_name, old_value, new_value,
                source, observed_at, valid_from, confidence_status
            ) VALUES (
                NEW.instrument_id,
                '{field}',
                OLD.{field}::TEXT,
                NEW.{field}::TEXT,
                COALESCE(
                    NEW.identity_sources->'{field}'->>'source',
                    'unknown'
                ),
                COALESCE(
                    (NEW.identity_sources->'{field}'->>'observed_at')::TIMESTAMPTZ,
                    NOW()
                ),
                NOW(),
                NEW.resolution_status::TEXT
            );
        END IF;""")

    trigger_body = "\n".join(field_checks)

    op.execute(f"""
        CREATE OR REPLACE FUNCTION trg_instrument_identity_history()
        RETURNS TRIGGER AS $$
        BEGIN
            {trigger_body}

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)

    op.execute("""
        CREATE TRIGGER instrument_identity_after_update
        AFTER UPDATE ON instrument_identity
        FOR EACH ROW
        EXECUTE FUNCTION trg_instrument_identity_history()
    """)

    # --- INSERT TRIGGER (initial history rows) ---
    insert_fields = []
    for field in _TRACKED_FIELDS:
        insert_fields.append(f"""
        IF NEW.{field} IS NOT NULL THEN
            INSERT INTO instrument_identity_history (
                instrument_id, field_name, old_value, new_value,
                source, observed_at, valid_from, confidence_status
            ) VALUES (
                NEW.instrument_id,
                '{field}',
                NULL,
                NEW.{field}::TEXT,
                COALESCE(
                    NEW.identity_sources->'{field}'->>'source',
                    'seed'
                ),
                COALESCE(
                    (NEW.identity_sources->'{field}'->>'observed_at')::TIMESTAMPTZ,
                    NOW()
                ),
                NOW(),
                NEW.resolution_status::TEXT
            );
        END IF;""")

    insert_body = "\n".join(insert_fields)

    op.execute(f"""
        CREATE OR REPLACE FUNCTION trg_instrument_identity_history_insert()
        RETURNS TRIGGER AS $$
        BEGIN
            {insert_body}

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)

    op.execute("""
        CREATE TRIGGER instrument_identity_after_insert
        AFTER INSERT ON instrument_identity
        FOR EACH ROW
        EXECUTE FUNCTION trg_instrument_identity_history_insert()
    """)


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS instrument_identity_after_insert "
        "ON instrument_identity"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS trg_instrument_identity_history_insert()"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS instrument_identity_after_update "
        "ON instrument_identity"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS trg_instrument_identity_history()"
    )
    op.execute("DROP TABLE IF EXISTS instrument_identity_history")
