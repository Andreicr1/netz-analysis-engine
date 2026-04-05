"""Upsert brochure_sections.csv and team_members.csv into database.

Reads CSVs produced by bulk_extract_brochures.py and upserts into
sec_manager_brochure_text and sec_manager_team tables.

Uses psycopg3 for fast batch operations.

Usage:
    cd backend
    python scripts/upsert_brochure_csvs.py \
        --sections /tmp/brochure_output/brochure_sections.csv \
        --team /tmp/brochure_output/team_members.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time

csv.field_size_limit(10_000_000)

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)


def get_connection_string() -> str:
    from app.core.config.settings import settings
    url = str(settings.database_url)
    return url.replace("postgresql+asyncpg://", "postgresql://")


SECTIONS_UPSERT = """
    INSERT INTO sec_manager_brochure_text (crd_number, section, filing_date, content)
    VALUES (%s, %s, %s, %s)
    ON CONFLICT (crd_number, section, filing_date)
    DO UPDATE SET content = EXCLUDED.content
"""

TEAM_UPSERT = """
    INSERT INTO sec_manager_team (crd_number, person_name, title, role,
        certifications, years_experience, bio_summary, data_fetched_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
    ON CONFLICT ON CONSTRAINT uq_sec_manager_team_crd_person
    DO UPDATE SET
        title = EXCLUDED.title,
        role = EXCLUDED.role,
        certifications = EXCLUDED.certifications,
        years_experience = EXCLUDED.years_experience,
        bio_summary = EXCLUDED.bio_summary,
        data_fetched_at = EXCLUDED.data_fetched_at
"""

BATCH_SIZE = 500


def _load_valid_crds(conn_str: str) -> set[str]:
    """Pre-load CRDs that exist in sec_managers (FK target)."""
    import psycopg

    with psycopg.connect(conn_str) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT crd_number FROM sec_managers")
            return {row[0] for row in cur.fetchall()}


def upsert_sections(conn_str: str, csv_path: str, valid_crds: set[str]) -> int:
    import psycopg

    print(f"Upserting sections from {csv_path}...")
    t0 = time.time()
    total = 0
    inserted = 0
    skipped_fk = 0

    with psycopg.connect(conn_str) as conn:
        conn.autocommit = False
        with conn.cursor() as cur:
            with open(csv_path, encoding="utf-8") as f:
                reader = csv.DictReader(f)

                for row in reader:
                    total += 1
                    crd = row["crd_number"]

                    if crd not in valid_crds:
                        skipped_fk += 1
                        continue

                    try:
                        cur.execute(SECTIONS_UPSERT, (
                            crd,
                            row["section"],
                            row["filing_date"],
                            row["content"],
                        ))
                    except Exception:
                        conn.rollback()
                        continue

                    inserted += 1
                    if inserted % 2000 == 0:
                        conn.commit()
                        elapsed = time.time() - t0
                        rate = inserted / elapsed if elapsed > 0 else 0
                        print(f"  sections: {inserted:,}/{total:,} inserted ({rate:.0f}/s, fk_skip={skipped_fk})")

            conn.commit()

    elapsed = time.time() - t0
    print(f"  DONE: {inserted:,} inserted, {skipped_fk} FK-skipped, {total:,} total in {elapsed:.0f}s")
    return inserted


def upsert_team(conn_str: str, csv_path: str, valid_crds: set[str]) -> int:
    import psycopg

    print(f"Upserting team from {csv_path}...")
    t0 = time.time()
    total = 0
    inserted = 0
    skipped_fk = 0

    with psycopg.connect(conn_str) as conn:
        conn.autocommit = False
        with conn.cursor() as cur:
            with open(csv_path, encoding="utf-8") as f:
                reader = csv.DictReader(f)

                for row in reader:
                    total += 1
                    crd = row["crd_number"]

                    if crd not in valid_crds:
                        skipped_fk += 1
                        continue

                    certs_raw = row.get("certifications", "")
                    certs = certs_raw.split("|") if certs_raw else None
                    years = int(row["years_experience"]) if row.get("years_experience") else None

                    try:
                        cur.execute(TEAM_UPSERT, (
                            crd,
                            row["person_name"],
                            row.get("title") or None,
                            row.get("role") or None,
                            certs,
                            years,
                            row.get("bio_summary") or None,
                        ))
                    except Exception:
                        conn.rollback()
                        continue

                    inserted += 1

            conn.commit()

    elapsed = time.time() - t0
    print(f"  DONE: {inserted:,} inserted, {skipped_fk} FK-skipped, {total:,} total in {elapsed:.0f}s")
    return inserted


def main() -> None:
    parser = argparse.ArgumentParser(description="Upsert brochure CSVs into database")
    parser.add_argument("--sections", required=True, help="Path to brochure_sections.csv")
    parser.add_argument("--team", required=True, help="Path to team_members.csv")
    parser.add_argument("--db-url", default=None,
                        help="Database URL override (default: from settings)")
    args = parser.parse_args()

    conn_str = args.db_url or get_connection_string()
    # Mask password for display
    display = conn_str[:30] + "...@" + conn_str.split("@")[-1] if "@" in conn_str else conn_str[:50]
    print(f"Target DB: {display}")
    print()

    t0 = time.time()

    print("Loading valid CRDs from sec_managers...")
    valid_crds = _load_valid_crds(conn_str)
    print(f"  {len(valid_crds):,} valid CRDs\n")

    if args.team and os.path.exists(args.team):
        upsert_team(conn_str, args.team, valid_crds)
        print()

    if args.sections and os.path.exists(args.sections):
        upsert_sections(conn_str, args.sections, valid_crds)

    print(f"\nTotal time: {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
