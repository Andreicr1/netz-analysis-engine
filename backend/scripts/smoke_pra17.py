"""PR-A17 post-merge smoke — does universe expansion flip any profile to phase_1?"""
import json
import time
from datetime import datetime, timezone

import httpx
import psycopg

PORTFOLIOS = [
    ("Conservative Preservation", "3945cee6-f85d-4903-a2dd-cf6a51e1c6a5"),
    ("Balanced Income", "e5892474-7438-4ac5-85da-217abcf99932"),
    ("Dynamic Growth", "3163d72b-3f8c-427e-9cd2-bead6377b59c"),
]
DEV_ACTOR = json.dumps({
    "actor_id": "smoke-a17", "name": "A17 Smoke", "email": "s@netz.capital",
    "roles": ["ADMIN", "INVESTMENT_TEAM"],
    "org_id": "403d8392-ebfa-5890-b740-45da49c556eb", "org_slug": "smoke",
})
HEADERS = {
    "X-DEV-ACTOR": DEV_ACTOR,
    "Content-Type": "application/json",
    "Idempotency-Key": datetime.now(timezone.utc).isoformat(),
}
DB = "postgresql://netz:netz@localhost:5434/netz_engine"

trigger_at = datetime.now(timezone.utc)
print(f"trigger_at={trigger_at.isoformat()}")
with httpx.Client(timeout=20.0) as c:
    for name, pid in PORTFOLIOS:
        r = c.post(f"http://localhost:8000/api/v1/portfolios/{pid}/build", headers=HEADERS, json={})
        print(f"[POST] {name} -> {r.status_code}")

deadline = time.time() + 180
while time.time() < deadline:
    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT pcr.status FROM portfolio_construction_runs pcr
            WHERE pcr.started_at >= %s AND pcr.portfolio_id IN (
                '3945cee6-f85d-4903-a2dd-cf6a51e1c6a5',
                'e5892474-7438-4ac5-85da-217abcf99932',
                '3163d72b-3f8c-427e-9cd2-bead6377b59c'
            )
        """, (trigger_at,))
        rows = cur.fetchall()
    terminal = [r for r in rows if r[0] in ("succeeded","failed","degraded","cancelled")]
    print(f"  poll: terminal={len(terminal)}/3")
    if len(terminal) >= 3:
        break
    time.sleep(8)

print("\n=== A17 POST-MERGE RESULT ===")
with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT DISTINCT ON (pcr.portfolio_id)
               mp.display_name, mp.profile, pcr.status,
               (pcr.calibration_snapshot->>'cvar_limit')::float AS limit,
               pcr.ex_ante_metrics->>'expected_return' AS er,
               pcr.ex_ante_metrics->>'cvar_95' AS cv,
               pcr.cascade_telemetry->>'cascade_summary' AS summary,
               pcr.cascade_telemetry->>'min_achievable_cvar' AS floor,
               (pcr.cascade_telemetry->'coverage'->>'pct_covered')::float AS coverage,
               pcr.cascade_telemetry->'operator_signal'->>'secondary' AS secondary
        FROM portfolio_construction_runs pcr
        JOIN model_portfolios mp ON mp.id = pcr.portfolio_id
        WHERE pcr.started_at >= %s
        ORDER BY pcr.portfolio_id, pcr.started_at DESC
    """, (trigger_at,))
    any_phase1 = False
    for r in cur.fetchall():
        name, profile, status, limit, er, cv, summary, floor, cov, sec = r
        flipped = summary == "phase_1_succeeded"
        if flipped:
            any_phase1 = True
        mark = "  ** FLIPPED TO PHASE 1 **" if flipped else ""
        print(f"\n--- {name} [{profile}] status={status}{mark}")
        print(f"    limit={float(limit)*100:.2f}%  delivered_CVaR={float(cv)*100:.2f}%  E[r]={float(er)*100:.2f}%" if cv and er else f"    limit={float(limit)*100:.2f}%")
        print(f"    universe_floor={float(floor)*100:.2f}%  coverage={cov*100:.1f}%  summary={summary}")
        print(f"    secondary_signal={'present' if sec not in (None,'null') else 'cleared'}")
    print(f"\n=== VERDICT: {'SUCCESS — at least one profile phase_1' if any_phase1 else 'STILL ALL DEGRADED — floor gap beyond coverage'} ===")
