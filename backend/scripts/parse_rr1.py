"""Parse RR1 (Risk/Return Summary) from DERA TSV → CSV files.

Step 1: Parse num.tsv from each quarter → returns.csv + stats.csv
Step 2: upsert_rr1.py loads CSVs into DB

Usage:
    cd backend
    python scripts/parse_rr1.py --parent "C:/Users/Andrei/Desktop/EDGAR FILES/RR1" --out "C:/Users/Andrei/Desktop/EDGAR FILES/rr1_parsed"
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time

csv.field_size_limit(10_000_000)

ANNUAL_RETURN_TAG = "AnnlRtrPct"

STAT_TAGS = {
    "ManagementFeesOverAssets": "management_fee_pct",
    "ExpensesOverAssets": "expense_ratio_pct",
    "NetExpensesOverAssets": "net_expense_ratio_pct",
    "FeeWaiverOrReimbursementOverAssets": "fee_waiver_pct",
    "DistributionAndService12b1FeesOverAssets": "distribution_12b1_pct",
    "AcquiredFundFeesAndExpensesOverAssets": "acquired_fund_fees_pct",
    "OtherExpensesOverAssets": "other_expenses_pct",
    "PortfolioTurnoverRate": "portfolio_turnover_pct",
    "ExpenseExampleYear01": "expense_example_1y",
    "ExpenseExampleYear03": "expense_example_3y",
    "ExpenseExampleYear05": "expense_example_5y",
    "ExpenseExampleYear10": "expense_example_10y",
    "BarChartHighestQuarterlyReturn": "bar_chart_best_qtr_pct",
    "BarChartLowestQuarterlyReturn": "bar_chart_worst_qtr_pct",
    "BarChartYearToDateReturn": "bar_chart_ytd_pct",
    "AverageAnnualTotalReturns1YearPercent": "avg_annual_return_1y",
    "AverageAnnualTotalReturns5YearsPercent": "avg_annual_return_5y",
    "AverageAnnualTotalReturns10YearsPercent": "avg_annual_return_10y",
}

STAT_COLS = [
    "series_id", "class_id", "filing_date",
    "management_fee_pct", "expense_ratio_pct", "net_expense_ratio_pct",
    "fee_waiver_pct", "distribution_12b1_pct", "acquired_fund_fees_pct",
    "other_expenses_pct", "portfolio_turnover_pct",
    "expense_example_1y", "expense_example_3y", "expense_example_5y", "expense_example_10y",
    "bar_chart_best_qtr_pct", "bar_chart_worst_qtr_pct", "bar_chart_ytd_pct",
    "avg_annual_return_1y", "avg_annual_return_5y", "avg_annual_return_10y",
]


def parse_quarter(rr1_dir: str) -> tuple[list[dict], list[dict]]:
    num_path = os.path.join(rr1_dir, "num.tsv")
    sub_path = os.path.join(rr1_dir, "sub.tsv")

    if not os.path.exists(num_path):
        return [], []

    # filing dates from sub.tsv
    filing_dates: dict[str, str] = {}
    if os.path.exists(sub_path):
        with open(sub_path, encoding="utf-8") as f:
            for r in csv.DictReader(f, delimiter="\t"):
                filed = r.get("filed", "").strip()
                if filed and len(filed) == 8:
                    filing_dates[r["adsh"]] = f"{filed[:4]}-{filed[4:6]}-{filed[6:8]}"
                elif filed and len(filed) == 10:
                    filing_dates[r["adsh"]] = filed

    annual_returns: list[dict] = []
    stats_accum: dict[tuple[str, str], dict] = {}

    with open(num_path, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            tag = r["tag"]
            series_id = r.get("series", "").strip()
            class_id = r.get("class", "").strip()
            value_str = r.get("value", "").strip()
            ddate = r.get("ddate", "")
            adsh = r.get("adsh", "")

            if not value_str:
                continue
            try:
                value = float(value_str)
            except (ValueError, TypeError):
                continue

            filing_date = filing_dates.get(adsh, "")

            # Annual returns
            if tag == ANNUAL_RETURN_TAG and series_id and ddate:
                year = int(ddate[:4])
                if year > 2000:
                    annual_returns.append({
                        "series_id": series_id,
                        "year": year,
                        "annual_return_pct": round(value, 6),
                        "filing_date": filing_date,
                    })
                continue

            # Stats
            if tag in STAT_TAGS:
                col = STAT_TAGS[tag]
                if col is None:
                    continue
                key = (series_id or "_none", class_id or "")
                if key not in stats_accum:
                    stats_accum[key] = {
                        "series_id": series_id or "",
                        "class_id": class_id or "",
                        "filing_date": filing_date,
                    }
                # Clamp extreme values
                if abs(value) < 1e8:
                    stats_accum[key][col] = round(value, 6)

    stats_rows = [
        row for row in stats_accum.values()
        if row.get("series_id") and row["series_id"] != "_none"
    ]

    return annual_returns, stats_rows


def main():
    parser = argparse.ArgumentParser(description="Parse RR1 DERA TSV → CSV")
    parser.add_argument("--parent", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)

    quarter_dirs = sorted(
        os.path.join(args.parent, d)
        for d in os.listdir(args.parent)
        if os.path.isdir(os.path.join(args.parent, d)) and "rr1" in d.lower()
    )

    print(f"{'=' * 60}")
    print(f"  RR1 Parser → CSV")
    print(f"  Quarters: {len(quarter_dirs)} | Output: {args.out}")
    print(f"{'=' * 60}")

    all_returns: list[dict] = []
    all_stats: list[dict] = []
    t_start = time.monotonic()

    for qi, qdir in enumerate(quarter_dirs, 1):
        qname = os.path.basename(qdir)
        returns, stats = parse_quarter(qdir)
        all_returns.extend(returns)
        all_stats.extend(stats)
        print(f"[{qi}/{len(quarter_dirs)}] {qname}: {len(returns):,} returns, {len(stats):,} stats")

    # Deduplicate returns: keep latest filing per (series_id, year)
    seen_returns: dict[tuple[str, int], dict] = {}
    for r in all_returns:
        key = (r["series_id"], r["year"])
        existing = seen_returns.get(key)
        if existing is None or r["filing_date"] > existing["filing_date"]:
            seen_returns[key] = r
    deduped_returns = list(seen_returns.values())

    # Deduplicate stats: keep latest filing per (series_id, class_id)
    seen_stats: dict[tuple[str, str], dict] = {}
    for s in all_stats:
        key = (s["series_id"], s["class_id"])
        existing = seen_stats.get(key)
        if existing is None or s.get("filing_date", "") > existing.get("filing_date", ""):
            seen_stats[key] = s
    deduped_stats = list(seen_stats.values())

    # Write returns CSV
    ret_path = os.path.join(args.out, "returns.csv")
    with open(ret_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["series_id", "year", "annual_return_pct", "filing_date"])
        w.writeheader()
        w.writerows(deduped_returns)

    # Write stats CSV
    stats_path = os.path.join(args.out, "stats.csv")
    with open(stats_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=STAT_COLS)
        w.writeheader()
        for row in deduped_stats:
            # Fill missing columns with empty string
            out = {c: row.get(c, "") for c in STAT_COLS}
            w.writerow(out)

    elapsed = time.monotonic() - t_start
    print(f"\n{'=' * 60}")
    print(f"  COMPLETE — {len(quarter_dirs)} quarters in {elapsed:.1f}s")
    print(f"  Returns: {len(deduped_returns):,} (from {len(all_returns):,} raw)")
    print(f"  Stats: {len(deduped_stats):,} (from {len(all_stats):,} raw)")
    print(f"  Output: {ret_path}")
    print(f"           {stats_path}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
