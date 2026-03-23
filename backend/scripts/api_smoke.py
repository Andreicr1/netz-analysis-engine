#!/usr/bin/env python3
"""
API Smoke Test — lightweight endpoint validation.

Runs against a live backend (localhost:8000 by default) using X-DEV-ACTOR
bypass. Tests that routes respond with expected status codes — not business
logic, just "is the endpoint wired up and not 500'ing?".

Usage:
    python scripts/api_smoke.py                    # default localhost:8000
    python scripts/api_smoke.py --base-url https://api.netz.app
    python scripts/api_smoke.py --vertical credit  # only credit endpoints
    python scripts/api_smoke.py --vertical wealth  # only wealth endpoints
    python scripts/api_smoke.py --verbose           # show response bodies
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass

import httpx

# ── Dev actor header ──────────────────────────────────────────────────
DEV_ORG_ID = "00000000-0000-0000-0000-000000000001"
DEV_FUND_ID = "00000000-0000-0000-0000-000000000099"

DEV_ACTOR = json.dumps({
    "actor_id": "smoke-test",
    "name": "Smoke Test",
    "email": "smoke@netz.capital",
    "roles": ["ADMIN", "SUPER_ADMIN"],
    "org_id": DEV_ORG_ID,
    "org_slug": "smoke-test-org",
})

HEADERS = {
    "X-DEV-ACTOR": DEV_ACTOR,
    "Content-Type": "application/json",
}


# ── Test definitions ──────────────────────────────────────────────────
@dataclass(frozen=True)
class Endpoint:
    method: str
    path: str
    expected: int | set[int]  # expected status code(s)
    group: str = "infra"
    body: dict | None = None
    desc: str = ""

    @property
    def ok_codes(self) -> set[int]:
        return self.expected if isinstance(self.expected, set) else {self.expected}


# Infra / Health
INFRA_ENDPOINTS = [
    Endpoint("GET", "/health", 200, "infra", desc="root health"),
    Endpoint("GET", "/api/health", 200, "infra", desc="api health"),
    Endpoint("GET", "/api/v1/admin/health/services", 200, "infra", desc="service health"),
    Endpoint("GET", "/api/v1/admin/health/workers", 200, "infra", desc="worker status"),
]

# Credit domain
CREDIT_ENDPOINTS = [
    # Dashboard
    Endpoint("GET", "/api/v1/dashboard/summary", {200, 404}, "credit", desc="dashboard summary"),
    Endpoint("GET", "/api/v1/dashboard/tasks", {200, 404}, "credit", desc="task inbox"),
    # Deals
    Endpoint("GET", f"/api/v1/funds/{DEV_FUND_ID}/deals", {200, 404}, "credit", desc="list deals"),
    # Portfolio (assets is POST-only for creation; GET uses fund_investments)
    Endpoint("GET", f"/api/v1/funds/{DEV_FUND_ID}/fund-investments", {200, 404}, "credit", desc="list fund investments"),
    Endpoint("GET", f"/api/v1/funds/{DEV_FUND_ID}/alerts", {200, 404}, "credit", desc="list alerts"),
    Endpoint("GET", f"/api/v1/funds/{DEV_FUND_ID}/obligations", {200, 404}, "credit", desc="list obligations"),
    # Documents
    Endpoint("GET", "/api/v1/documents/search?query=test&domain=IC_MEMO", {200, 404, 422}, "credit", desc="vector search"),
    # Reports (report-packs listing uses the reporting router)
    Endpoint("GET", f"/api/v1/funds/{DEV_FUND_ID}/reports", {200, 404}, "credit", desc="list reports"),
    # IC Memos
    Endpoint("GET", f"/api/v1/funds/{DEV_FUND_ID}/ic-memos", {200, 404}, "credit", desc="list IC memos"),
    # Dataroom
    Endpoint("GET", f"/api/v1/funds/{DEV_FUND_ID}/dataroom/tree", {200, 404}, "credit", desc="dataroom tree"),
]

# Wealth domain
WEALTH_ENDPOINTS = [
    # Instruments
    Endpoint("GET", "/api/v1/instruments", {200}, "wealth", desc="list instruments"),
    Endpoint("GET", "/api/v1/instruments?limit=5", {200}, "wealth", desc="instruments paginated"),
    # Portfolios
    Endpoint("GET", "/api/v1/portfolios", {200}, "wealth", desc="list portfolios"),
    # Screener
    Endpoint("GET", "/api/v1/screener/results", {200, 404}, "wealth", desc="screener results"),
    # DD Reports
    Endpoint("GET", "/api/v1/dd-reports", {200, 404}, "wealth", desc="list DD reports"),
    # Model Portfolios
    Endpoint("GET", "/api/v1/model-portfolios", {200}, "wealth", desc="model portfolios"),
    # Macro
    Endpoint("GET", "/api/v1/macro/overview", {200, 404}, "wealth", desc="macro overview"),
    Endpoint("GET", "/api/v1/macro/regional", {200, 404}, "wealth", desc="regional macro"),
    # Strategy Drift
    Endpoint("GET", "/api/v1/strategy-drift/alerts", {200, 404}, "wealth", desc="drift alerts"),
    # Universe
    Endpoint("GET", "/api/v1/universe/approvals", {200, 404}, "wealth", desc="universe approvals"),
    # Content
    Endpoint("GET", "/api/v1/content/reports", {200, 404}, "wealth", desc="content reports"),
    # Workers status
    Endpoint("GET", "/api/v1/workers/status", {200, 404}, "wealth", desc="workers status"),
]

# Admin domain
ADMIN_ENDPOINTS = [
    Endpoint("GET", "/api/v1/admin/tenants", {200}, "admin", desc="list tenants"),
    Endpoint("GET", "/api/v1/admin/configs/credit/analysis_profile", {200, 400, 404}, "admin", desc="credit config"),
    Endpoint("GET", "/api/v1/admin/configs/wealth/analysis_profile", {200, 400, 404}, "admin", desc="wealth config"),
    Endpoint("GET", "/api/v1/admin/audit?limit=5", {200}, "admin", desc="audit events"),
    Endpoint("GET", "/api/v1/admin/prompts?vertical=credit", {200, 404}, "admin", desc="credit prompts"),
    Endpoint("GET", "/api/v1/admin/inspect/lake-stats", {200, 404, 501}, "admin", desc="lake stats"),
]

ALL_ENDPOINTS = INFRA_ENDPOINTS + CREDIT_ENDPOINTS + WEALTH_ENDPOINTS + ADMIN_ENDPOINTS


# ── Runner ────────────────────────────────────────────────────────────
@dataclass
class Result:
    endpoint: Endpoint
    status: int
    elapsed_ms: float
    passed: bool
    error: str | None = None
    body: str = ""


def run_smoke(
    base_url: str,
    vertical: str | None = None,
    verbose: bool = False,
    timeout: float = 10.0,
) -> list[Result]:
    endpoints = ALL_ENDPOINTS
    if vertical:
        groups = {"infra", vertical}
        endpoints = [e for e in ALL_ENDPOINTS if e.group in groups]

    results: list[Result] = []
    client = httpx.Client(base_url=base_url, headers=HEADERS, timeout=timeout, follow_redirects=True)

    print(f"\n{'='*60}")
    print(f"  API Smoke Test — {base_url}")
    print(f"  Endpoints: {len(endpoints)} | Vertical: {vertical or 'all'}")
    print(f"{'='*60}\n")

    current_group = ""
    for ep in endpoints:
        if ep.group != current_group:
            current_group = ep.group
            print(f"  [{current_group.upper()}]")

        t0 = time.perf_counter()
        try:
            resp = client.request(ep.method, ep.path, json=ep.body)
            elapsed = (time.perf_counter() - t0) * 1000
            passed = resp.status_code in ep.ok_codes
            result = Result(
                endpoint=ep,
                status=resp.status_code,
                elapsed_ms=elapsed,
                passed=passed,
                body=resp.text[:500] if verbose else "",
            )
        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            result = Result(
                endpoint=ep,
                status=0,
                elapsed_ms=elapsed,
                passed=False,
                error=str(exc),
            )

        icon = "PASS" if result.passed else "FAIL"
        color = "\033[32m" if result.passed else "\033[31m"
        reset = "\033[0m"
        expect_str = ",".join(str(c) for c in sorted(ep.ok_codes))

        print(f"    {color}{icon}{reset}  {ep.method:5} {ep.path:<55} "
              f"{result.status:>3} (expect {expect_str}) {result.elapsed_ms:>6.0f}ms "
              f"  {ep.desc}")

        if result.error:
            print(f"          ERROR: {result.error}")
        if verbose and result.body:
            print(f"          BODY: {result.body[:200]}")

        results.append(result)

    client.close()
    return results


def print_summary(results: list[Result]) -> bool:
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    total = len(results)
    avg_ms = sum(r.elapsed_ms for r in results) / total if total else 0

    print(f"\n{'='*60}")
    if failed == 0:
        print(f"  \033[32mALL {total} ENDPOINTS PASSED\033[0m  (avg {avg_ms:.0f}ms)")
    else:
        print(f"  \033[31m{failed} FAILED\033[0m / {total} total  (avg {avg_ms:.0f}ms)")
        print("\n  Failed endpoints:")
        for r in results:
            if not r.passed:
                expect_str = ",".join(str(c) for c in sorted(r.endpoint.ok_codes))
                print(f"    {r.endpoint.method:5} {r.endpoint.path}")
                print(f"          got {r.status}, expected {expect_str}")
                if r.error:
                    print(f"          {r.error}")
    print(f"{'='*60}\n")

    return failed == 0


# ── CLI ───────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="API Smoke Test")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Backend base URL")
    parser.add_argument("--vertical", choices=["credit", "wealth", "admin"], help="Only test one vertical")
    parser.add_argument("--verbose", action="store_true", help="Show response bodies")
    parser.add_argument("--timeout", type=float, default=10.0, help="Request timeout in seconds")
    args = parser.parse_args()

    try:
        results = run_smoke(args.base_url, args.vertical, args.verbose, args.timeout)
    except httpx.ConnectError:
        print(f"\n\033[31mERROR: Cannot connect to {args.base_url}\033[0m")
        print("Start the backend with: make serve\n")
        sys.exit(2)

    ok = print_summary(results)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
