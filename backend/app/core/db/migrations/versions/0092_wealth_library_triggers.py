"""Wealth Library — sync triggers from source tables into the index.

Phase 1.1 of the Wealth Library sprint
(docs/superpowers/specs/2026-04-08-wealth-library.md §4.1).

Final migration of the Library data layer foundation. Creates three
PL/pgSQL functions (one per source table) and six triggers (two per
source table — combined INSERT+DELETE plus UPDATE-with-WHEN) that
keep ``wealth_library_index`` transactionally synchronised with
``wealth_content``, ``dd_reports`` and ``macro_reviews``.

Architectural decisions
=======================

Why two triggers per table instead of one
-----------------------------------------

PostgreSQL forbids the WHEN clause from referencing both NEW and OLD
unless the trigger fires only on UPDATE (INSERT has no OLD, DELETE
has no NEW). To exploit ``WHEN (NEW.* IS DISTINCT FROM OLD.*)`` for
the no-op short-circuit on UPDATE, the UPDATE trigger must be
separate from the INSERT/DELETE trigger:

  * ``sync_<source>_insert_delete`` — AFTER INSERT OR DELETE, no WHEN
  * ``sync_<source>_update``        — AFTER UPDATE WHEN (...)

Both call the same function which dispatches on TG_OP.

Why ON CONFLICT upsert
----------------------

Treating INSERT and UPDATE symmetrically through ON CONFLICT (source_
table, source_id, organization_id) DO UPDATE means the function code
is shorter and re-applying it idempotently after a worker rebuild
(900_080) is safe.

Why backfill direct via INSERT...SELECT
---------------------------------------

The source-tables -> index triggers we just installed only fire on
new writes. Existing rows in the source tables need to be backfilled
once. Going through the trigger by issuing dummy UPDATEs would fire
six triggers per row and pollute the audit log; instead we run
INSERT...SELECT directly into the index, bypassing the source-table
trigger path. The bulk insert temporarily disables FORCE ROW LEVEL
SECURITY on the index (mirroring migration 0030's pattern for
audit_events) so the migration user can write rows for every tenant
without setting per-row session GUCs.

Folder path conventions (must match the trigger PL/pgSQL exactly)
=================================================================

  Investment Outlook   ['Macro & Outlook', 'Investment Outlook',  YYYY-Qn]
  Flash Report         ['Macro & Outlook', 'Flash Reports',       YYYY-MM]
  Manager Spotlight    ['Due Diligence',   'Manager Spotlights']
  DD Report (full)     ['Due Diligence',   'By Fund', <name>, 'v' || version]
  DD Report (bond)     ['Due Diligence',   'Bond Briefs', <name>]
  Macro Review         ['Macro & Outlook', 'Weekly Macro Reviews', YYYY-"W"IW]

  When status IN ('draft','review','pending_approval','rejected',
                  'failed','generating') the path is prefixed with
  'Drafts & Pending'.

Revision ID: 0092_wealth_library_triggers
Revises: 0091_wealth_library_pins
Create Date: 2026-04-08 16:30:00.000000
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0092_wealth_library_triggers"
down_revision: str | None = "0091_wealth_library_pins"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ── Shared SQL fragment for the "drafts & pending" prefix logic ──
# Used in three places (the three trigger functions). Defined here as
# a Python constant so the rule lives in exactly one place.
_DRAFT_STATUS_PREDICATE = (
    "v_status_lower IN ('draft', 'review', 'pending_approval', "
    "'rejected', 'failed', 'generating')"
)


def upgrade() -> None:
    # ───────────────────────────────────────────────────────────────
    # 1. Trigger function — wealth_content -> wealth_library_index
    # ───────────────────────────────────────────────────────────────
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sync_wealth_content_to_library_index()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_folder_path  text[];
            v_status_lower text;
        BEGIN
            -- DELETE: just propagate the deletion to the index.
            IF TG_OP = 'DELETE' THEN
                DELETE FROM wealth_library_index
                WHERE source_table = 'wealth_content'
                  AND source_id = OLD.id
                  AND organization_id = OLD.organization_id;
                RETURN OLD;
            END IF;

            -- INSERT or UPDATE: build the canonical row and upsert.
            v_status_lower := lower(coalesce(NEW.status, ''));

            -- Build folder_path from content_type. Manager spotlights
            -- belong under Due Diligence; outlooks/flash reports under
            -- Macro & Outlook; everything else falls back to Other.
            CASE NEW.content_type
                WHEN 'investment_outlook' THEN
                    v_folder_path := ARRAY[
                        'Macro & Outlook',
                        'Investment Outlook',
                        to_char(NEW.created_at, 'YYYY-"Q"Q')
                    ];
                WHEN 'flash_report' THEN
                    v_folder_path := ARRAY[
                        'Macro & Outlook',
                        'Flash Reports',
                        to_char(NEW.created_at, 'YYYY-MM')
                    ];
                WHEN 'manager_spotlight' THEN
                    v_folder_path := ARRAY[
                        'Due Diligence',
                        'Manager Spotlights'
                    ];
                ELSE
                    v_folder_path := ARRAY['Other', NEW.content_type];
            END CASE;

            -- Drafts & pending overlay
            IF v_status_lower IN ('draft', 'review', 'pending_approval',
                                  'rejected', 'failed', 'generating') THEN
                v_folder_path := ARRAY['Drafts & Pending'] || v_folder_path;
            END IF;

            INSERT INTO wealth_library_index (
                organization_id, source_table, source_id,
                kind, title, subtitle,
                status, language, version, is_current,
                entity_kind, entity_id, entity_slug, entity_label,
                folder_path, author_id, approver_id,
                approved_at, created_at, updated_at,
                confidence_score, decision_anchor, storage_path, metadata
            ) VALUES (
                NEW.organization_id, 'wealth_content', NEW.id,
                NEW.content_type, NEW.title, NULL,
                NEW.status, NEW.language, NULL, true,
                NULL, NULL, NULL, NULL,
                v_folder_path, NEW.created_by, NEW.approved_by,
                NEW.approved_at, NEW.created_at, NEW.updated_at,
                NULL, NULL, NEW.storage_path,
                jsonb_build_object('content_type', NEW.content_type)
            )
            ON CONFLICT (source_table, source_id, organization_id)
            DO UPDATE SET
                kind         = EXCLUDED.kind,
                title        = EXCLUDED.title,
                status       = EXCLUDED.status,
                language     = EXCLUDED.language,
                folder_path  = EXCLUDED.folder_path,
                author_id    = EXCLUDED.author_id,
                approver_id  = EXCLUDED.approver_id,
                approved_at  = EXCLUDED.approved_at,
                updated_at   = EXCLUDED.updated_at,
                storage_path = EXCLUDED.storage_path,
                metadata     = EXCLUDED.metadata;

            RETURN NEW;
        END;
        $$;
        """,
    )

    # ───────────────────────────────────────────────────────────────
    # 2. Trigger function — dd_reports -> wealth_library_index
    # ───────────────────────────────────────────────────────────────
    # DD reports do NOT have an `updated_at` column, only created_at.
    # We synthesise updated_at as COALESCE(approved_at, created_at)
    # so the index reflects the most recent meaningful event time.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sync_dd_reports_to_library_index()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_entity_label text;
            v_entity_slug  text;
            v_kind         text;
            v_title        text;
            v_folder_path  text[];
            v_status_lower text;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                DELETE FROM wealth_library_index
                WHERE source_table = 'dd_reports'
                  AND source_id = OLD.id
                  AND organization_id = OLD.organization_id;
                RETURN OLD;
            END IF;

            -- Resolve instrument name + slug for the title and the
            -- folder path. instruments_universe is the global catalog;
            -- the slug column comes from migration 0090.
            SELECT name, slug
              INTO v_entity_label, v_entity_slug
            FROM instruments_universe
            WHERE instrument_id = NEW.instrument_id;

            v_entity_label := coalesce(v_entity_label, 'Unknown Instrument');
            v_kind         := coalesce(NEW.report_type, 'dd_report');
            v_status_lower := lower(coalesce(NEW.status, ''));

            -- Title format depends on report_type
            IF v_kind = 'bond_brief' THEN
                v_title := v_entity_label || ' — Bond Brief';
                v_folder_path := ARRAY[
                    'Due Diligence',
                    'Bond Briefs',
                    v_entity_label
                ];
            ELSE
                v_title := v_entity_label || ' — DD Report v' || NEW.version::text;
                v_folder_path := ARRAY[
                    'Due Diligence',
                    'By Fund',
                    v_entity_label,
                    'v' || NEW.version::text
                ];
            END IF;

            -- Drafts & pending overlay
            IF v_status_lower IN ('draft', 'review', 'pending_approval',
                                  'rejected', 'failed', 'generating') THEN
                v_folder_path := ARRAY['Drafts & Pending'] || v_folder_path;
            END IF;

            INSERT INTO wealth_library_index (
                organization_id, source_table, source_id,
                kind, title, subtitle,
                status, language, version, is_current,
                entity_kind, entity_id, entity_slug, entity_label,
                folder_path, author_id, approver_id,
                approved_at, created_at, updated_at,
                confidence_score, decision_anchor, storage_path, metadata
            ) VALUES (
                NEW.organization_id, 'dd_reports', NEW.id,
                v_kind, v_title, NULL,
                NEW.status, NEW.pdf_language, NEW.version, NEW.is_current,
                'instrument', NEW.instrument_id, v_entity_slug, v_entity_label,
                v_folder_path, NEW.created_by, NEW.approved_by,
                NEW.approved_at, NEW.created_at,
                coalesce(NEW.approved_at, NEW.created_at),
                NEW.confidence_score, NEW.decision_anchor, NEW.storage_path,
                jsonb_build_object(
                    'report_type', NEW.report_type,
                    'schema_version', NEW.schema_version,
                    'rejection_reason', NEW.rejection_reason
                )
            )
            ON CONFLICT (source_table, source_id, organization_id)
            DO UPDATE SET
                kind             = EXCLUDED.kind,
                title            = EXCLUDED.title,
                status           = EXCLUDED.status,
                language         = EXCLUDED.language,
                version          = EXCLUDED.version,
                is_current       = EXCLUDED.is_current,
                entity_slug      = EXCLUDED.entity_slug,
                entity_label     = EXCLUDED.entity_label,
                folder_path      = EXCLUDED.folder_path,
                approver_id      = EXCLUDED.approver_id,
                approved_at      = EXCLUDED.approved_at,
                updated_at       = EXCLUDED.updated_at,
                confidence_score = EXCLUDED.confidence_score,
                decision_anchor  = EXCLUDED.decision_anchor,
                storage_path     = EXCLUDED.storage_path,
                metadata         = EXCLUDED.metadata;

            RETURN NEW;
        END;
        $$;
        """,
    )

    # ───────────────────────────────────────────────────────────────
    # 3. Trigger function — macro_reviews -> wealth_library_index
    # ───────────────────────────────────────────────────────────────
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sync_macro_reviews_to_library_index()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_week_label   text;
            v_title        text;
            v_folder_path  text[];
            v_status_lower text;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                DELETE FROM wealth_library_index
                WHERE source_table = 'macro_reviews'
                  AND source_id = OLD.id
                  AND organization_id = OLD.organization_id;
                RETURN OLD;
            END IF;

            v_week_label   := to_char(NEW.as_of_date, 'IYYY-"W"IW');
            v_title        := v_week_label || ' — Macro Committee Review';
            v_status_lower := lower(coalesce(NEW.status, ''));

            v_folder_path := ARRAY[
                'Macro & Outlook',
                'Weekly Macro Reviews',
                v_week_label
            ];

            -- pending/rejected reviews go to Drafts & Pending
            IF v_status_lower IN ('draft', 'pending', 'review',
                                  'pending_approval', 'rejected') THEN
                v_folder_path := ARRAY['Drafts & Pending'] || v_folder_path;
            END IF;

            INSERT INTO wealth_library_index (
                organization_id, source_table, source_id,
                kind, title, subtitle,
                status, language, version, is_current,
                entity_kind, entity_id, entity_slug, entity_label,
                folder_path, author_id, approver_id,
                approved_at, created_at, updated_at,
                confidence_score, decision_anchor, storage_path, metadata
            ) VALUES (
                NEW.organization_id, 'macro_reviews', NEW.id,
                'macro_review', v_title, v_week_label,
                NEW.status, NULL, NULL, true,
                NULL, NULL, NULL, NULL,
                v_folder_path, NEW.created_by, NEW.approved_by,
                NEW.approved_at, NEW.created_at, NEW.updated_at,
                NULL, NULL, NULL,
                jsonb_build_object(
                    'as_of_date', NEW.as_of_date,
                    'is_emergency', NEW.is_emergency,
                    'snapshot_id', NEW.snapshot_id,
                    'decision_rationale', NEW.decision_rationale
                )
            )
            ON CONFLICT (source_table, source_id, organization_id)
            DO UPDATE SET
                title       = EXCLUDED.title,
                subtitle    = EXCLUDED.subtitle,
                status      = EXCLUDED.status,
                folder_path = EXCLUDED.folder_path,
                author_id   = EXCLUDED.author_id,
                approver_id = EXCLUDED.approver_id,
                approved_at = EXCLUDED.approved_at,
                updated_at  = EXCLUDED.updated_at,
                metadata    = EXCLUDED.metadata;

            RETURN NEW;
        END;
        $$;
        """,
    )

    # ───────────────────────────────────────────────────────────────
    # 4. Attach the triggers — two per source table
    # ───────────────────────────────────────────────────────────────
    # The combined INSERT OR DELETE trigger has no WHEN clause —
    # both NEW (for INSERT) and OLD (for DELETE) are well-defined
    # and the function dispatches on TG_OP. The UPDATE trigger uses
    # WHEN (NEW.* IS DISTINCT FROM OLD.*) so no-op updates skip the
    # function entirely (the optimisation called out in the brief).

    for source_table, function_name in (
        ("wealth_content", "sync_wealth_content_to_library_index"),
        ("dd_reports", "sync_dd_reports_to_library_index"),
        ("macro_reviews", "sync_macro_reviews_to_library_index"),
    ):
        op.execute(
            f"DROP TRIGGER IF EXISTS sync_{source_table}_library_index_iud "
            f"ON {source_table}",
        )
        op.execute(
            f"""
            CREATE TRIGGER sync_{source_table}_library_index_iud
            AFTER INSERT OR DELETE ON {source_table}
            FOR EACH ROW
            EXECUTE FUNCTION {function_name}();
            """,
        )
        op.execute(
            f"DROP TRIGGER IF EXISTS sync_{source_table}_library_index_upd "
            f"ON {source_table}",
        )
        op.execute(
            f"""
            CREATE TRIGGER sync_{source_table}_library_index_upd
            AFTER UPDATE ON {source_table}
            FOR EACH ROW
            WHEN (NEW.* IS DISTINCT FROM OLD.*)
            EXECUTE FUNCTION {function_name}();
            """,
        )

    # ───────────────────────────────────────────────────────────────
    # 5. Backfill existing rows from each source table
    # ───────────────────────────────────────────────────────────────
    # Temporarily lift FORCE ROW LEVEL SECURITY so the migration
    # user can insert rows for every tenant in a single bulk pass —
    # mirrors the audit_events approach in migration 0030. RLS is
    # re-enabled at the end.
    op.execute("ALTER TABLE wealth_library_index NO FORCE ROW LEVEL SECURITY")

    # 5a. wealth_content backfill
    op.execute(
        """
        INSERT INTO wealth_library_index (
            organization_id, source_table, source_id,
            kind, title, subtitle,
            status, language, version, is_current,
            entity_kind, entity_id, entity_slug, entity_label,
            folder_path, author_id, approver_id,
            approved_at, created_at, updated_at,
            confidence_score, decision_anchor, storage_path, metadata
        )
        SELECT
            wc.organization_id,
            'wealth_content',
            wc.id,
            wc.content_type,
            wc.title,
            NULL,
            wc.status,
            wc.language,
            NULL,
            true,
            NULL, NULL, NULL, NULL,
            CASE
                WHEN lower(coalesce(wc.status, '')) IN
                     ('draft','review','pending_approval','rejected','failed','generating') THEN
                    ARRAY['Drafts & Pending'] ||
                    CASE wc.content_type
                        WHEN 'investment_outlook' THEN
                            ARRAY['Macro & Outlook', 'Investment Outlook',
                                  to_char(wc.created_at, 'YYYY-"Q"Q')]
                        WHEN 'flash_report' THEN
                            ARRAY['Macro & Outlook', 'Flash Reports',
                                  to_char(wc.created_at, 'YYYY-MM')]
                        WHEN 'manager_spotlight' THEN
                            ARRAY['Due Diligence', 'Manager Spotlights']
                        ELSE
                            ARRAY['Other', wc.content_type]
                    END
                ELSE
                    CASE wc.content_type
                        WHEN 'investment_outlook' THEN
                            ARRAY['Macro & Outlook', 'Investment Outlook',
                                  to_char(wc.created_at, 'YYYY-"Q"Q')]
                        WHEN 'flash_report' THEN
                            ARRAY['Macro & Outlook', 'Flash Reports',
                                  to_char(wc.created_at, 'YYYY-MM')]
                        WHEN 'manager_spotlight' THEN
                            ARRAY['Due Diligence', 'Manager Spotlights']
                        ELSE
                            ARRAY['Other', wc.content_type]
                    END
            END AS folder_path,
            wc.created_by,
            wc.approved_by,
            wc.approved_at,
            wc.created_at,
            wc.updated_at,
            NULL, NULL, wc.storage_path,
            jsonb_build_object('content_type', wc.content_type)
        FROM wealth_content wc
        ON CONFLICT (source_table, source_id, organization_id) DO NOTHING;
        """,
    )

    # 5b. dd_reports backfill — joins instruments_universe for slug/name
    op.execute(
        """
        INSERT INTO wealth_library_index (
            organization_id, source_table, source_id,
            kind, title, subtitle,
            status, language, version, is_current,
            entity_kind, entity_id, entity_slug, entity_label,
            folder_path, author_id, approver_id,
            approved_at, created_at, updated_at,
            confidence_score, decision_anchor, storage_path, metadata
        )
        SELECT
            dr.organization_id,
            'dd_reports',
            dr.id,
            coalesce(dr.report_type, 'dd_report'),
            CASE coalesce(dr.report_type, 'dd_report')
                WHEN 'bond_brief' THEN
                    coalesce(iu.name, 'Unknown Instrument') || ' — Bond Brief'
                ELSE
                    coalesce(iu.name, 'Unknown Instrument')
                    || ' — DD Report v' || dr.version::text
            END,
            NULL,
            dr.status,
            dr.pdf_language,
            dr.version,
            dr.is_current,
            'instrument',
            dr.instrument_id,
            iu.slug,
            coalesce(iu.name, 'Unknown Instrument'),
            CASE
                WHEN lower(coalesce(dr.status, '')) IN
                     ('draft','review','pending_approval','rejected','failed','generating') THEN
                    ARRAY['Drafts & Pending'] ||
                    CASE coalesce(dr.report_type, 'dd_report')
                        WHEN 'bond_brief' THEN
                            ARRAY['Due Diligence', 'Bond Briefs',
                                  coalesce(iu.name, 'Unknown Instrument')]
                        ELSE
                            ARRAY['Due Diligence', 'By Fund',
                                  coalesce(iu.name, 'Unknown Instrument'),
                                  'v' || dr.version::text]
                    END
                ELSE
                    CASE coalesce(dr.report_type, 'dd_report')
                        WHEN 'bond_brief' THEN
                            ARRAY['Due Diligence', 'Bond Briefs',
                                  coalesce(iu.name, 'Unknown Instrument')]
                        ELSE
                            ARRAY['Due Diligence', 'By Fund',
                                  coalesce(iu.name, 'Unknown Instrument'),
                                  'v' || dr.version::text]
                    END
            END AS folder_path,
            dr.created_by,
            dr.approved_by,
            dr.approved_at,
            dr.created_at,
            coalesce(dr.approved_at, dr.created_at) AS updated_at,
            dr.confidence_score,
            dr.decision_anchor,
            dr.storage_path,
            jsonb_build_object(
                'report_type', dr.report_type,
                'schema_version', dr.schema_version,
                'rejection_reason', dr.rejection_reason
            )
        FROM dd_reports dr
        LEFT JOIN instruments_universe iu
               ON iu.instrument_id = dr.instrument_id
        ON CONFLICT (source_table, source_id, organization_id) DO NOTHING;
        """,
    )

    # 5c. macro_reviews backfill
    op.execute(
        """
        INSERT INTO wealth_library_index (
            organization_id, source_table, source_id,
            kind, title, subtitle,
            status, language, version, is_current,
            entity_kind, entity_id, entity_slug, entity_label,
            folder_path, author_id, approver_id,
            approved_at, created_at, updated_at,
            confidence_score, decision_anchor, storage_path, metadata
        )
        SELECT
            mr.organization_id,
            'macro_reviews',
            mr.id,
            'macro_review',
            to_char(mr.as_of_date, 'IYYY-"W"IW') || ' — Macro Committee Review',
            to_char(mr.as_of_date, 'IYYY-"W"IW'),
            mr.status,
            NULL,
            NULL,
            true,
            NULL, NULL, NULL, NULL,
            CASE
                WHEN lower(coalesce(mr.status, '')) IN
                     ('draft','pending','review','pending_approval','rejected') THEN
                    ARRAY['Drafts & Pending', 'Macro & Outlook',
                          'Weekly Macro Reviews',
                          to_char(mr.as_of_date, 'IYYY-"W"IW')]
                ELSE
                    ARRAY['Macro & Outlook', 'Weekly Macro Reviews',
                          to_char(mr.as_of_date, 'IYYY-"W"IW')]
            END AS folder_path,
            mr.created_by,
            mr.approved_by,
            mr.approved_at,
            mr.created_at,
            mr.updated_at,
            NULL, NULL, NULL,
            jsonb_build_object(
                'as_of_date', mr.as_of_date,
                'is_emergency', mr.is_emergency,
                'snapshot_id', mr.snapshot_id,
                'decision_rationale', mr.decision_rationale
            )
        FROM macro_reviews mr
        ON CONFLICT (source_table, source_id, organization_id) DO NOTHING;
        """,
    )

    # Re-enable FORCE ROW LEVEL SECURITY now that backfill is done.
    op.execute("ALTER TABLE wealth_library_index FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    # Drop triggers BEFORE dropping the functions they reference.
    for source_table in ("wealth_content", "dd_reports", "macro_reviews"):
        op.execute(
            f"DROP TRIGGER IF EXISTS sync_{source_table}_library_index_upd "
            f"ON {source_table}",
        )
        op.execute(
            f"DROP TRIGGER IF EXISTS sync_{source_table}_library_index_iud "
            f"ON {source_table}",
        )

    op.execute("DROP FUNCTION IF EXISTS sync_macro_reviews_to_library_index()")
    op.execute("DROP FUNCTION IF EXISTS sync_dd_reports_to_library_index()")
    op.execute("DROP FUNCTION IF EXISTS sync_wealth_content_to_library_index()")

    # Truncate the index — the data was derived from sources, no
    # original information is lost. Future re-application of the
    # migration will re-populate via backfill.
    op.execute("TRUNCATE wealth_library_index")
