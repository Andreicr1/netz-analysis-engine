"""Backfill fund_type in sec_manager_funds via checkbox image detection.

Parses ADV Part 1 PDFs using PyMuPDF to detect checked Q10 checkboxes
(different image xref = checked vs unchecked), then writes a JSONL file
for bulk DB update via Tiger MCP or asyncpg.

Usage:
    python -m scripts.backfill_fund_type          # parse + save JSONL
    python -m scripts.backfill_fund_type --workers 20  # custom parallelism
"""
from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

PDF_DIR = Path(__file__).resolve().parent.parent.parent / ".data" / "adv_part1" / "pdfs"
OUTPUT = Path(__file__).resolve().parent.parent.parent / ".data" / "adv_part1" / "fund_type_fixes.jsonl"

# ── Q10 checkbox image detection ─────────────────────────────────

_Q10_LABELS: list[tuple[str, str]] = [
    ("hedge fund", "Hedge Fund"),
    ("liquidity fund", "Liquidity Fund"),
    ("private equity fund", "Private Equity Fund"),
    ("real estate fund", "Real Estate Fund"),
    ("securitized asset fund", "Securitized Asset Fund"),
    ("venture capital fund", "Venture Capital Fund"),
]

_FUND_NAME_RE = re.compile(
    r"Name of the private fund:\s*\n\s*(.+?)(?:\n|$)", re.IGNORECASE,
)


def _detect_on_page(page) -> str | None:  # noqa: ANN001
    """Detect checked fund type on a single PDF page via image xrefs."""
    blocks = page.get_text("dict")
    labels: list[tuple[str, float, float]] = []
    for block in blocks.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                t = span["text"].strip().lower()
                bbox = span["bbox"]
                for kw, lbl in _Q10_LABELS:
                    if t == kw:
                        labels.append((lbl, bbox[0], bbox[1]))
                        break
                if labels and t.startswith("other") and abs(bbox[1] - labels[0][2]) < 2:
                    labels.append(("Other Private Fund", bbox[0], bbox[1]))

    if len(labels) < 5:
        return None

    q10_y = labels[0][2]
    checkboxes: list[tuple[float, int]] = []
    for img in page.get_image_info(xrefs=True):
        if img["width"] <= 20 and img["height"] <= 25:
            if abs(img["bbox"][1] - q10_y + 8) < 15:
                checkboxes.append((img["bbox"][0], img["xref"]))

    if len(checkboxes) < 6:
        return None

    xref_counts = Counter(xr for _, xr in checkboxes)
    if len(xref_counts) < 2:
        return None

    unchecked_xref = xref_counts.most_common(1)[0][0]
    checked = [(x, xr) for x, xr in checkboxes if xr != unchecked_xref]
    if not checked:
        return None

    cx = checked[0][0]
    nearest = min(labels, key=lambda t: abs(t[1] - cx - 15))
    return nearest[0]


def process_one_pdf(pdf_path_str: str) -> list[dict]:
    """Process a single PDF — designed to run in a worker process."""
    import fitz  # import inside worker to avoid pickling issues

    pdf_path = Path(pdf_path_str)
    crd = pdf_path.stem
    results: list[dict] = []

    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        return [{"crd": crd, "_status": "error"}]

    try:
        full_text = "\n".join(page.get_text("text") for page in doc)
        if "SECTION 7.B.(1)" not in full_text:
            return [{"crd": crd, "_status": "no_section"}]

        # Detect fund types via checkbox images per page
        page_types: dict[int, str] = {}
        for pn in range(len(doc)):
            page = doc[pn]
            text = page.get_text("text")
            if "what type of fund" not in text.lower():
                continue
            ft = _detect_on_page(page)
            if ft:
                page_types[pn] = ft

        ordered_types = [page_types[p] for p in sorted(page_types)] if page_types else []

        # Extract Section 7.B.(1)
        start = full_text.index("SECTION 7.B.(1)")
        end = len(full_text)
        for marker in ["SECTION 7.B.(2)", "Item 8 ", "SCHEDULE A", "Schedule A"]:
            idx = full_text.find(marker, start + 100)
            if idx != -1 and idx < end:
                end = idx

        section_text = full_text[start:end]
        sections = re.split(r"A\.\s*PRIVATE FUND\b", section_text)

        for fidx, section in enumerate(sections[1:]):
            m = _FUND_NAME_RE.search(section)
            if not m:
                continue
            fund_name = m.group(1).strip()
            fund_type = ordered_types[fidx] if fidx < len(ordered_types) else None
            results.append({
                "crd": crd,
                "fund_name": fund_name,
                "fund_type": fund_type,
            })
    except Exception as e:
        return [{"crd": crd, "_status": "error", "_msg": str(e)[:100]}]
    finally:
        doc.close()

    return results if results else [{"crd": crd, "_status": "no_funds"}]


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill fund_type via checkbox image detection")
    parser.add_argument("--workers", type=int, default=20, help="Number of parallel workers")
    parser.add_argument("--pdf-dir", type=str, help="Override PDF directory")
    args = parser.parse_args()

    pdf_dir = Path(args.pdf_dir) if args.pdf_dir else PDF_DIR
    pdf_files = sorted(str(p) for p in pdf_dir.glob("*.pdf"))
    total = len(pdf_files)

    print(f"Parsing {total} PDFs with {args.workers} workers...")
    t0 = time.time()

    all_results: list[dict] = []
    type_dist: Counter[str] = Counter()
    ok = fail = no_section = errors = 0

    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for batch_results in pool.map(process_one_pdf, pdf_files, chunksize=50):
            for r in batch_results:
                status = r.get("_status")
                if status == "no_section":
                    no_section += 1
                elif status == "error":
                    errors += 1
                elif status == "no_funds":
                    pass
                elif r.get("fund_type"):
                    all_results.append(r)
                    type_dist[r["fund_type"]] += 1
                    ok += 1
                else:
                    fail += 1

            # Progress every ~1000 PDFs
            processed = ok + fail + no_section + errors
            if processed % 1000 < 50:
                elapsed = time.time() - t0
                print(f"  progress ~{processed}/{total} ({elapsed:.0f}s) ok={ok} fail={fail}")

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s ({total} PDFs, {args.workers} workers)")
    print(f"Funds: ok={ok}, fail={fail}, no_section={no_section}, errors={errors}")
    print("Type distribution:")
    for t, c in type_dist.most_common():
        print(f"  {t}: {c}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        for r in all_results:
            f.write(json.dumps({
                "crd": r["crd"],
                "fund_name": r["fund_name"],
                "fund_type": r["fund_type"],
            }, ensure_ascii=False) + "\n")

    print(f"\nSaved {len(all_results)} fixes to {OUTPUT}")


if __name__ == "__main__":
    main()
