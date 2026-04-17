"""PR-A12.3 verification — cvar_within_limit must be True post-fix."""
import json
import time
from datetime import datetime, timezone

import httpx
import psycopg

PORTFOLIOS = [
    ("Conservative Preservation", "3945cee6-f85d-4903-a2dd-cf6a51e1c6a5", 0.025),
    ("Balanced Income", "e5892474-7438-4ac5-85da-217abcf99932", 0.05),
    ("Dynamic Growth", "3163d72b-3f8c-427e-9cd2-bead6377b59c", 0.08),
]
DEV_ACTOR = json.dumps({
    "actor_id": "smoke-a123", "name": "A12.3 Smoke", "email": "s@netz.capital",
    "roles": ["ADMIN", "INVESTMENT_TEAM"],
    "org_id": "403d8392-ebfa-5890-b740-45da49c556eb", "org_slug": "smoke",
})
HEADERS = {"X-DEV-ACTOR": DEV_ACTOR, "Content-Type": "application/json"}
DB = "postgresql://netz:netz@localhost:5434/netz_engine"

trigger_at = datetime.now(timezone.utc)
print(f"trigger_at={trigger_at.isoformat()}")
with httpx.Client(timeout=20.0) as c:
    for name, pid, _ in PORTFOLIOS:
        r = c.post(f"http://localhost:8000/api/v1/portfolios/{pid}/build", headers=HEADERS, json={})
        print(f"[POST] {name} -> {r.status_code}")

deadline = time.time() + 180
while time.time() < deadline:
    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT mp.id::text, pcr.status FROM portfolio_construction_runs pcr
            JOIN model_portfolios mp ON mp.id=pcr.portfolio_id
            WHERE pcr.started_at >= %s AND mp.id IN (
                '3945cee6-f85d-4903-a2dd-cf6a51e1c6a5',
                'e5892474-7438-4ac5-85da-217abcf99932',
                '3163d72b-3f8c-427e-9cd2-bead6377b59c'
            )
        """, (trigger_at,))
        rows = cur.fetchall()
    terminal = [r for r in rows if r[1] in ("succeeded","failed","degraded","cancelled")]
    print(f"  poll: terminal={len(terminal)}/3")
    if len(terminal) >= 3:
        break
    time.sleep(8)

print("\n=== A12.3 PASS-CRITERIA EVALUATION ===")
with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT mp.display_name, pcr.status,
               pcr.optimizer_trace->>'solver' AS solver,
               pcr.cascade_telemetry->>'cascade_summary' AS summary,
               pcr.cascade_telemetry->'achievable_return_band' AS band,
               (pcr.calibration_snapshot->>'cvar_limit')::float AS limit,
               pcr.ex_ante_metrics->>'cvar_95' AS cvar_95
        FROM portfolio_construction_runs pcr
        JOIN model_portfolios mp ON mp.id=pcr.portfolio_id
        WHERE pcr.started_at >= %s
        ORDER BY pcr.started_at DESC
    """, (trigger_at,))
    all_pass = True
    for r in cur.fetchall():
        name, status, solver, summary, band, limit, cvar_raw = r
        cvar = abs(float(cvar_raw)) if cvar_raw else None
        within = cvar is not None and limit is not None and cvar <= limit + 1e-3
        flag = "PASS" if within and status in ("succeeded", "degraded") else "FAIL"
        all_pass = all_pass and (flag == "PASS")
        cvar_str = f"{cvar:.4f}" if cvar is not None else "None"
        limit_str = f"{limit:.4f}" if limit is not None else "None"
        print(f"\n  [{flag}] {name}")
        print(f"    status={status}  solver={solver}  summary={summary}")
        print(f"    cvar_delivered={cvar_str}  cvar_limit={limit_str}  within={within}")
        print(f"    band={json.dumps(band)}")

print(f"\n{'=== OVERALL: PASS ===' if all_pass else '=== OVERALL: FAIL ==='}")
