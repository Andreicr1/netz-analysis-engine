"""Parse RR-1 lab.tsv to extract benchmark names declared by MF prospectuses.

lab.tsv columns: adsh, tag, version, std, terse, verbose, total, negated, negatedTerse

Strategy:
  1. Read sub.tsv → adsh → cik mapping
  2. Read lab.tsv → find *Member tags (dimensional labels) where std label
     contains a benchmark provider keyword AND does NOT contain "Fund"
  3. Aggregate unique benchmarks per CIK
  4. Cross-reference with DB sec_registered_funds MF CIKs
"""
import asyncio
import os
import re
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

load_dotenv(".env")

TICKERS_DIR = Path(r"E:\EDGAR FILES\Tickers")

# Benchmark provider keywords — if label contains any of these, it's likely a benchmark name
BENCHMARK_PROVIDERS = re.compile(
    r"\b(S&P|Russell|MSCI|Bloomberg|FTSE|Nasdaq|Dow Jones|Wilshire|CRSP|ICE|BofA|Barclays|"
    r"Citigroup|JPMorgan|JP Morgan|Invesco|NASDAQ|NYSE|LBMA|BBG|Schwab|STOXX|NIKKEI|TOPIX|"
    r"Lipper|Morningstar|Refinitiv|Reuters)\b",
    re.IGNORECASE,
)

# Exclude labels containing "Fund" (those are fund names, not benchmarks)
FUND_NAME = re.compile(r"\bFund\b", re.IGNORECASE)

# Must end with or contain "Index" to qualify
INDEX_WORD = re.compile(r"\bindex\b", re.IGNORECASE)


def clean_label(label: str) -> str:
    """Strip XBRL decorators like [Member], [Text Block], etc."""
    label = re.sub(r"\[[^\]]+\]", "", label).strip()
    label = re.sub(r"\s+", " ", label)
    return label


def is_benchmark_label(tag: str, label: str) -> bool:
    """True if this label looks like a benchmark name declaration."""
    if not label or len(label) < 10 or len(label) > 250:
        return False
    # Must be a dimensional Member (custom benchmark dimension)
    if "Member" not in tag:
        return False
    # Must mention a benchmark provider
    if not BENCHMARK_PROVIDERS.search(label):
        return False
    # Must contain "Index" word
    if not INDEX_WORD.search(label):
        return False
    # Must NOT be a fund name
    if FUND_NAME.search(label):
        return False
    return True


def normalize_benchmark(label: str) -> str:
    """Canonicalize a benchmark label for deduplication."""
    label = clean_label(label)
    # Strip SEC disclosure boilerplate
    label = re.sub(
        r"\s*\(reflects\s+no\s+deduct(?:ions?|s)\s+for[^)]*\)",
        "",
        label,
        flags=re.IGNORECASE,
    )
    label = re.sub(r"\s*\(net of[^)]+\)", "", label, flags=re.IGNORECASE)
    label = re.sub(r"\s*\([^)]{0,30}\)", "", label)  # Remove short parens
    # Trailing ® or ™ or SM
    label = re.sub(r"[®™]|SM\b", "", label)
    label = re.sub(r"\s+", " ", label).strip()
    return label


# Step 1 — parse sub.tsv
print("Parsing sub.tsv (adsh -> cik)...")
adsh_to_cik: dict[str, str] = {}
with open(TICKERS_DIR / "sub.tsv", encoding="utf-8") as f:
    header = f.readline().strip().split("\t")
    adsh_idx = header.index("adsh")
    cik_idx = header.index("cik")
    for line in f:
        parts = line.rstrip("\n").split("\t")
        if len(parts) > max(adsh_idx, cik_idx):
            adsh = parts[adsh_idx]
            cik = parts[cik_idx]
            if adsh and cik:
                adsh_to_cik[adsh] = cik.lstrip("0")
print(f"  filings: {len(adsh_to_cik):,}")

# Step 2 — parse lab.tsv for benchmark labels
print("\nParsing lab.tsv for benchmark Member labels...")
cik_benchmarks: dict[str, set[str]] = defaultdict(set)
total_members = 0
benchmark_hits = 0
with open(TICKERS_DIR / "lab.tsv", encoding="utf-8", errors="replace") as f:
    header = f.readline().strip().split("\t")
    # adsh tag version std terse verbose total negated negatedTerse
    label_candidate_indices = [3, 4, 5]  # std, terse, verbose
    for line in f:
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 6:
            continue
        adsh = parts[0]
        tag = parts[1]
        if "Member" not in tag:
            continue
        total_members += 1
        # Try std → terse → verbose, take first match
        for idx in label_candidate_indices:
            if idx >= len(parts):
                continue
            label = parts[idx]
            if is_benchmark_label(tag, label):
                norm = normalize_benchmark(label)
                cik = adsh_to_cik.get(adsh)
                if cik and norm:
                    cik_benchmarks[cik].add(norm)
                    benchmark_hits += 1
                break

print(f"  total *Member rows scanned: {total_members:,}")
print(f"  benchmark label hits:        {benchmark_hits:,}")
print(f"  unique CIKs with benchmark:  {len(cik_benchmarks):,}")

# Top 20 most common benchmarks
from collections import Counter

freq = Counter()
for benches in cik_benchmarks.values():
    for b in benches:
        freq[b] += 1
print("\nTop 20 benchmarks (by CIK count):")
for bench, count in freq.most_common(20):
    print(f"  {count:4d}  {bench[:100]}")


async def main() -> None:
    url = os.getenv("DATABASE_URL")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    eng = create_async_engine(url)
    async with eng.begin() as conn:
        r = await conn.execute(text(
            "SELECT cik FROM sec_registered_funds WHERE fund_type = 'mutual_fund'"
        ))
        db_mf = {row[0] for row in r}
        r = await conn.execute(text("""
            SELECT cik FROM sec_registered_funds
            WHERE fund_type = 'mutual_fund' AND primary_benchmark IS NOT NULL
        """))
        db_with_bench = {row[0] for row in r}
    await eng.dispose()

    def fsds_covers(c: str) -> bool:
        for v in {c, c.lstrip("0"), c.zfill(10)}:
            if v in cik_benchmarks:
                return True
        return False

    covered = sum(1 for c in db_mf if fsds_covers(c))
    gap = db_mf - db_with_bench
    covered_gap = sum(1 for c in gap if fsds_covers(c))

    print()
    print("=" * 60)
    print("COVERAGE — Q1 2025 RR-1 slice vs DB MFs")
    print("=" * 60)
    print(f"DB MF total:                {len(db_mf):,}")
    print(f"DB MF with primary_benchmark today: {len(db_with_bench):,} ({100*len(db_with_bench)/len(db_mf):.1f}%)")
    print(f"DB MF covered by FSDS lab:  {covered:,} ({100*covered/len(db_mf):.1f}%)")
    print(f"Gap filled by FSDS:         {covered_gap:,}/{len(gap):,} = {100*covered_gap/len(gap):.1f}%")
    print(f"Projected total coverage:   {len(db_with_bench) + covered_gap:,}/{len(db_mf):,} = {100*(len(db_with_bench)+covered_gap)/len(db_mf):.1f}%")

asyncio.run(main())
