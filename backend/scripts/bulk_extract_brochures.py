"""Bulk extract ADV Part 2A brochure PDFs → two CSVs.

Reads PDFs from local directories, extracts text (PyMuPDF), classifies
sections (regex), parses team members (Part 2B), and writes:
  - brochure_sections.csv  → sec_manager_brochure_text
  - team_members.csv       → sec_manager_team

Uses ProcessPoolExecutor with 20 workers for CPU-bound PDF extraction.

Usage:
    cd backend
    python scripts/bulk_extract_brochures.py \
        "C:/Projetos/EDGAR/ADV_Brochures_2026_March_1_of_2" \
        "C:/Projetos/EDGAR/ADV_Brochures_2026_March_2_of_2"

    # Optional: filter to catalog managers only
    python scripts/bulk_extract_brochures.py --catalog-only \
        "C:/Projetos/EDGAR/ADV_Brochures_2026_March_1_of_2" \
        "C:/Projetos/EDGAR/ADV_Brochures_2026_March_2_of_2"
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

WORKERS = 20


# ── Dataclasses for results ──────────────────────────────────────


@dataclass
class SectionRow:
    crd_number: str
    section: str
    filing_date: str
    content: str


@dataclass
class TeamRow:
    crd_number: str
    person_name: str
    title: str
    role: str
    certifications: str  # pipe-separated
    years_experience: str
    bio_summary: str


# ── PDF extraction (runs in worker process) ──────────────────────


def _extract_one(args: tuple[str, str]) -> tuple[list[SectionRow], list[TeamRow]]:
    """Extract sections + team from a single PDF. Runs in subprocess."""
    crd, pdf_path = args

    try:
        import fitz  # pymupdf

        doc = fitz.open(pdf_path)
        pages = [page.get_text("text") for page in doc]
        doc.close()
        full_text = "\n\n".join(p for p in pages if p.strip())

        if len(full_text) < 100:
            return [], []

        sections = _classify_sections(crd, full_text)
        team = _parse_team(crd, full_text)
        return sections, team

    except Exception as exc:
        print(f"  ERROR CRD {crd}: {exc}", file=sys.stderr)
        return [], []


# ── Section classification (same logic as adv_service.py) ────────

import re

_SECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("advisory_business", re.compile(r"item\s*4.*advisory\s*business", re.IGNORECASE)),
    ("fees_compensation", re.compile(r"item\s*5.*fees\s*and\s*compensation", re.IGNORECASE)),
    ("performance_fees", re.compile(r"item\s*6.*performance.based\s*fees", re.IGNORECASE)),
    ("client_types", re.compile(r"item\s*7.*types\s*of\s*clients", re.IGNORECASE)),
    ("methods_of_analysis", re.compile(r"item\s*8.*methods\s*of\s*analysis", re.IGNORECASE)),
    ("investment_philosophy", re.compile(r"item\s*8.*investment\s*strateg", re.IGNORECASE)),
    ("disciplinary", re.compile(r"item\s*9.*disciplinary\s*information", re.IGNORECASE)),
    ("other_activities", re.compile(r"item\s*10.*other\s*financial\s*industry", re.IGNORECASE)),
    ("code_of_ethics", re.compile(r"item\s*11.*code\s*of\s*ethics", re.IGNORECASE)),
    ("brokerage_practices", re.compile(r"item\s*12.*brokerage\s*practices", re.IGNORECASE)),
    ("review_of_accounts", re.compile(r"item\s*13.*review\s*of\s*accounts", re.IGNORECASE)),
    ("client_referrals", re.compile(r"item\s*14.*client\s*referrals", re.IGNORECASE)),
    ("custody", re.compile(r"item\s*15.*custody", re.IGNORECASE)),
    ("investment_discretion", re.compile(r"item\s*16.*investment\s*discretion", re.IGNORECASE)),
    ("voting_securities", re.compile(r"item\s*17.*voting\s*client\s*securities", re.IGNORECASE)),
    ("financial_information", re.compile(r"item\s*18.*financial\s*information", re.IGNORECASE)),
    ("risk_management", re.compile(r"item\s*8.*risk\s*of\s*loss", re.IGNORECASE)),
]

# Minimum content length to distinguish real sections from TOC entries
_MIN_SECTION_CONTENT = 200


def _classify_sections(crd: str, full_text: str) -> list[SectionRow]:
    """Split brochure into classified sections, skipping TOC entries."""
    from datetime import date

    today = date.today().isoformat()

    # Find all section boundaries
    boundaries: list[tuple[int, str]] = []
    for section_key, pattern in _SECTION_PATTERNS:
        for m in pattern.finditer(full_text):
            boundaries.append((m.start(), section_key))

    if not boundaries:
        # No structured sections — store full text
        if len(full_text.strip()) > 100:
            return [SectionRow(crd, "full_brochure", today, full_text.strip()[:50000])]
        return []

    # Sort by position, extract text between boundaries
    boundaries.sort(key=lambda x: x[0])
    sections: list[SectionRow] = []
    seen: set[str] = set()

    for i, (start, key) in enumerate(boundaries):
        end = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(full_text)
        content = full_text[start:end].strip()

        # Skip TOC entries (short) and duplicates (keep longest per section)
        if len(content) < _MIN_SECTION_CONTENT:
            continue

        if key in seen:
            # Replace if this one is longer (TOC was seen first, real content after)
            for j, s in enumerate(sections):
                if s.section == key and len(content) > len(s.content):
                    sections[j] = SectionRow(crd, key, today, content[:50000])
            continue

        seen.add(key)
        sections.append(SectionRow(crd, key, today, content[:50000]))

    return sections


# ── Team parsing ─────────────────────────────────────────────────
#
# Two complementary patterns to catch different Part 2B formats:
#
# Pattern A (original): "FirstName LastName, Title/Designation..."
#   e.g. "John Smith, CFA, Portfolio Manager"
#
# Pattern B (SEC standard Part 2B): "FirstName LastName (birth_year)"
#   followed by education and "Mr./Ms. LastName is Title"
#   e.g. "Neil Gilfedder (1971)\nB.A. Philosophy...\nMr. Gilfedder is EVP"

_TEAM_PERSON_RE = re.compile(
    r"^(?:##?\s*)?([A-Z][a-z]+(?:[ \t]+[A-Z]\.?[ \t]*[a-z]+){1,3})"
    r"(?:[ \t]*,[ \t]*|[ \t]*\n[ \t]*)"
    r"((?:CFA|CFP|CAIA|CPA|MBA|PhD|JD|CIO|CEO|Managing\s+Director|"
    r"Portfolio\s+Manager|President|Vice\s+President|Director|Partner|"
    r"Senior\s+Vice|Chief)[^\n]{0,80})",
    re.MULTILINE,
)

# Part 2B standard format: "Name (year)"
_TEAM_PART2B_RE = re.compile(
    r"^([A-Z][a-z]+(?:[ \t]+[A-Z]\.?)?(?:[ \t]+[A-Z][a-z]+){1,3})"
    r"\s*\((\d{4})\)",
    re.MULTILINE,
)

_CERTIFICATION_RE = re.compile(r"\b(CFA|CFP|CAIA|CPA|FRM|CIPM)\b")
_EXPERIENCE_RE = re.compile(
    r"(\d{1,2})\s*(?:\+\s*)?years?\s*(?:of\s*)?(?:experience|in\s*the\s*industry)",
    re.IGNORECASE,
)

# "Mr./Ms./Mrs./Dr. LastName is Title"
_TITLE_IS_RE = re.compile(
    r"(?:Mr|Ms|Mrs|Dr)\.?\s+\w+\s+is\s+(.*?)(?:\.|$)",
    re.MULTILINE,
)


def _parse_team(crd: str, full_text: str) -> list[TeamRow]:
    """Extract team members from Part 2B brochure supplement."""
    members: list[TeamRow] = []
    seen_names: set[str] = set()

    def _add_member(
        name: str, title: str, context: str, bio_start: int,
    ) -> None:
        name_key = name.lower()
        if name_key in seen_names:
            return
        seen_names.add(name_key)

        certs = sorted(set(_CERTIFICATION_RE.findall(context)))
        years = ""
        exp_match = _EXPERIENCE_RE.search(context)
        if exp_match:
            years = exp_match.group(1)

        bio_raw = full_text[bio_start:bio_start + 400].strip()
        # Cut at next person entry (Name (year) or double newline)
        next_person = re.search(
            r"\n[A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]+\s*\(\d{4}\)", bio_raw,
        )
        if next_person:
            bio_raw = bio_raw[:next_person.start()]
        para_break = bio_raw.find("\n\n")
        if para_break > 0:
            bio_raw = bio_raw[:para_break]
        bio = bio_raw.strip() if len(bio_raw) > 20 else ""

        members.append(TeamRow(
            crd_number=crd,
            person_name=name,
            title=title or "",
            role="",
            certifications="|".join(certs),
            years_experience=years,
            bio_summary=bio,
        ))

    # Pattern A: "Name, Title/Designation"
    for match in _TEAM_PERSON_RE.finditer(full_text):
        name = match.group(1).strip()
        title = match.group(2).strip().rstrip(",.")
        ctx_start = max(0, match.start() - 50)
        ctx_end = min(len(full_text), match.end() + 500)
        _add_member(name, title, full_text[ctx_start:ctx_end], match.end())

    # Pattern B: "Name (year)" — Part 2B standard
    for match in _TEAM_PART2B_RE.finditer(full_text):
        name = match.group(1).strip()
        # Look for "Mr./Ms. LastName is Title" in the next 500 chars
        ctx_end = min(len(full_text), match.end() + 500)
        context = full_text[match.end():ctx_end]

        title = ""
        title_match = _TITLE_IS_RE.search(context)
        if title_match:
            title = title_match.group(1).strip().rstrip(".")

        _add_member(name, title, full_text[match.start():ctx_end], match.end())

    return members


# ── Main ─────────────────────────────────────────────────────────


def collect_pdfs(
    directories: list[str],
    catalog_crds: set[str] | None = None,
) -> dict[str, str]:
    """Map CRD → latest PDF path. If catalog_crds provided, filter to those."""
    crd_to_path: dict[str, str] = {}
    for d in directories:
        for f in os.listdir(d):
            if not f.endswith(".pdf"):
                continue
            crd = f.split("_")[0]
            if catalog_crds is not None and crd not in catalog_crds:
                continue
            # Keep the latest file per CRD (lexicographic sort by date in filename)
            if crd not in crd_to_path or f > os.path.basename(crd_to_path[crd]):
                crd_to_path[crd] = os.path.join(d, f)
    return crd_to_path


def get_catalog_crds() -> set[str]:
    """Fetch catalog manager CRDs from database."""
    import asyncio

    from sqlalchemy import text

    from app.core.db.engine import async_session_factory

    async def _fetch() -> set[str]:
        async with async_session_factory() as db:
            r = await db.execute(text(
                "SELECT DISTINCT manager_id FROM mv_unified_funds "
                "WHERE manager_id IS NOT NULL"
            ))
            return {row[0] for row in r.all()}

    return asyncio.run(_fetch())


def main() -> None:
    parser = argparse.ArgumentParser(description="Bulk extract ADV brochures → CSV")
    parser.add_argument("directories", nargs="+", help="Directories containing PDFs")
    parser.add_argument("--catalog-only", action="store_true",
                        help="Only process CRDs that are in the fund catalog")
    parser.add_argument("--workers", type=int, default=WORKERS,
                        help=f"Parallel workers (default: {WORKERS})")
    parser.add_argument("--output-dir", default=".", help="Output directory for CSVs")
    args = parser.parse_args()

    # Validate directories
    for d in args.directories:
        if not os.path.isdir(d):
            print(f"ERROR: {d} is not a directory", file=sys.stderr)
            sys.exit(1)

    # Collect PDFs
    catalog_crds = None
    if args.catalog_only:
        print("Loading catalog CRDs from database...")
        catalog_crds = get_catalog_crds()
        print(f"  Catalog managers: {len(catalog_crds):,}")

    print("Scanning PDF directories...")
    crd_to_path = collect_pdfs(args.directories, catalog_crds)
    print(f"  PDFs to process: {len(crd_to_path):,}")

    if not crd_to_path:
        print("Nothing to process.")
        return

    # Prepare output files
    os.makedirs(args.output_dir, exist_ok=True)
    sections_path = os.path.join(args.output_dir, "brochure_sections.csv")
    team_path = os.path.join(args.output_dir, "team_members.csv")

    # Process with multiprocessing
    tasks = list(crd_to_path.items())
    total = len(tasks)
    t0 = time.time()

    all_sections: list[SectionRow] = []
    all_team: list[TeamRow] = []
    done = 0
    errors = 0

    print(f"Extracting with {args.workers} workers...")

    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_extract_one, task): task[0] for task in tasks}

        for future in as_completed(futures):
            crd = futures[future]
            done += 1
            try:
                sections, team = future.result()
                all_sections.extend(sections)
                all_team.extend(team)
            except Exception as exc:
                errors += 1
                print(f"  FAILED CRD {crd}: {exc}", file=sys.stderr)

            if done % 500 == 0 or done == total:
                elapsed = time.time() - t0
                rate = done / elapsed if elapsed > 0 else 0
                eta = (total - done) / rate if rate > 0 else 0
                print(
                    f"  [{done:,}/{total:,}] "
                    f"{rate:.0f} PDFs/s | "
                    f"sections={len(all_sections):,} team={len(all_team):,} "
                    f"errors={errors} | "
                    f"ETA {eta:.0f}s"
                )

    elapsed = time.time() - t0

    # Write CSVs
    print(f"\nWriting {sections_path}...")
    with open(sections_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["crd_number", "section", "filing_date", "content"])
        for s in all_sections:
            w.writerow([s.crd_number, s.section, s.filing_date, s.content])

    print(f"Writing {team_path}...")
    with open(team_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["crd_number", "person_name", "title", "role",
                     "certifications", "years_experience", "bio_summary"])
        for t in all_team:
            w.writerow([t.crd_number, t.person_name, t.title, t.role,
                        t.certifications, t.years_experience, t.bio_summary])

    # Summary
    unique_section_crds = len({s.crd_number for s in all_sections})
    unique_team_crds = len({t.crd_number for t in all_team})
    section_dist: dict[str, int] = {}
    for s in all_sections:
        section_dist[s.section] = section_dist.get(s.section, 0) + 1

    print(f"\n{'='*60}")
    print(f"DONE in {elapsed:.0f}s ({elapsed/60:.1f}min)")
    print(f"  PDFs processed: {done:,} ({errors} errors)")
    print(f"  Sections extracted: {len(all_sections):,} from {unique_section_crds:,} managers")
    print(f"  Team members extracted: {len(all_team):,} from {unique_team_crds:,} managers")
    print("\nSection distribution:")
    for section, cnt in sorted(section_dist.items(), key=lambda x: -x[1]):
        print(f"  {section:25s} {cnt:>6,}")
    print("\nOutput:")
    print(f"  {sections_path} ({os.path.getsize(sections_path)/1024/1024:.1f} MB)")
    print(f"  {team_path} ({os.path.getsize(team_path)/1024:.1f} KB)")


if __name__ == "__main__":
    main()
