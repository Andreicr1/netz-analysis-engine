# PR-A12.2 — Profile-Differentiated CVaR Defaults

**Branch:** `feat/pr-a12-2-cvar-profile-defaults` (cut from `main` post-A12.1 merge).
**Estimated effort:** ~45-60 minutes.
**Predecessor:** PR-A12 #191 (always-solvable RU CVaR cascade) + PR-A12.1 (cleanup).
**Source memory:** `C:\Users\andre\.claude\projects\C--Users-andre-projetos-netz-analysis-engine\memory\project_cvar_profile_differentiation.md`.

---

## Context

Verified empirically on local DB 2026-04-16: all 3 canonical model_portfolios (Conservative Preservation, Balanced Income, Dynamic Growth) share `portfolio_calibration.cvar_limit = 0.0500`. The differentiator across profiles is only `strategic_allocation` block weights, not the risk budget. This is the seed-level defect that caused Conservative + Balanced to silently fall to Phase 3 min_variance_fallback pre-A12.

**Pre-A12 (variance proxy):** σ_max = (0.05/2.85)² ≈ 1.75% — infeasible for FI-heavy Conservative (universe floor σ ≈ 3%) → Phase 3 fallback (CVaR-blind).

**Post-A12 (RU LP):** RU constraint applied directly. Conservative now hits Phase 1 with band [9.84%, 30.62%] at 5% CVaR limit. But the CVaR limit itself is still wrong institutionally: a Conservative IPS expects tighter tail-loss containment (typically 2-3%), Growth allows more (8-10%).

**Why this matters now (sequencing):** PR-A13 (frontend Builder slider) will let operators adjust `cvar_limit` per portfolio. The slider's default position should reflect the profile's institutional norm, not a uniform 5%. A13 is the consumer; A12.2 is the upstream fix that makes A13's defaults sensible.

Per memory `feedback_optimizer_always_solvable.md`: defaults are starting points the operator adjusts, not fixed seeds. A12.2 sets the starting points; A13 exposes the slider.

---

## Recommended defaults (operator can override per portfolio in A13)

| Profile | Current | Proposed cvar_limit | Rationale |
|---|---|---|---|
| `conservative` | 5.0% | **2.5%** | Capital preservation mandate; tail-loss containment |
| `moderate` | 5.0% | **5.0%** (no change) | Balanced risk/return |
| `growth` | 5.0% | **8.0%** | Accepts tail risk for return |
| `aggressive` (if exists) | — | **10.0%** | Full risk-on |

`cvar_level` stays 0.95 (95% CVaR) across all profiles — that's the academic standard, not a profile-differentiated parameter.

---

## Architecture decision: helper function + creation logic + backfill migration

Three coordinated pieces (all small):

### 1. Helper function (single source of truth)

New module-level function in `backend/app/domains/wealth/models/model_portfolio.py` (next to `PortfolioCalibration` class):

```python
# Profile-differentiated CVaR defaults — institutional starting points.
# Operators override per portfolio via the calibration update endpoint
# (admin UI: PR-A13 Builder slider).
_CVAR_DEFAULT_BY_PROFILE: dict[str, Decimal] = {
    "conservative": Decimal("0.0250"),
    "moderate": Decimal("0.0500"),
    "growth": Decimal("0.0800"),
    "aggressive": Decimal("0.1000"),
}


def default_cvar_limit_for_profile(profile: str | None) -> Decimal:
    """Return the institutional CVaR_95 starting default for a profile.

    Falls back to 0.05 (moderate) when the profile is unknown so that
    code paths without a profile (legacy fixtures, future profiles
    not yet calibrated) get a safe value rather than KeyError.
    """
    if profile is None:
        return Decimal("0.0500")
    return _CVAR_DEFAULT_BY_PROFILE.get(profile.lower(), Decimal("0.0500"))
```

Use `Decimal` to match the existing `cvar_limit` column type (Numeric(6,4)). Verify the import — `from decimal import Decimal` likely already at top of file.

### 2. Creation-site updates (two places)

**`backend/app/domains/wealth/routes/model_portfolios.py:254`** — `create_portfolio`:

Today the constructor is:
```python
calibration = PortfolioCalibration(
    organization_id=org_uuid,
    portfolio_id=portfolio.id,
    updated_by=actor.actor_id,
)
```

Update to pass the profile-derived CVaR (when no `source_calibration` to clone from):
```python
from app.domains.wealth.models.model_portfolio import default_cvar_limit_for_profile

calibration = PortfolioCalibration(
    organization_id=org_uuid,
    portfolio_id=portfolio.id,
    updated_by=actor.actor_id,
    cvar_limit=default_cvar_limit_for_profile(portfolio.profile),
)
```

The `if source_calibration is not None:` branch (lines 259-281) ALREADY copies `cvar_limit` from the source — keep as-is. The profile-default only applies to fresh portfolios with no clone source.

**`backend/app/domains/wealth/routes/model_portfolios.py:666`** — `_ensure_calibration`:

Today:
```python
row = PortfolioCalibration(
    organization_id=org_uuid,
    portfolio_id=portfolio_id,
)
```

Need to fetch the portfolio profile first (it's not currently loaded in this helper). Two options:
- (a) Add `profile: str` parameter and require all callers to pass it. Cleaner.
- (b) Look up the portfolio in this helper. Adds one query.

Lock **(a)**. Update signature:
```python
async def _ensure_calibration(
    db: AsyncSession,
    portfolio_id: uuid.UUID,
    organization_id: uuid.UUID | str,
    profile: str | None = None,  # PR-A12.2: profile-differentiated CVaR default
) -> PortfolioCalibration:
```

Body:
```python
row = PortfolioCalibration(
    organization_id=org_uuid,
    portfolio_id=portfolio_id,
    cvar_limit=default_cvar_limit_for_profile(profile),
)
```

Audit ALL callers of `_ensure_calibration` (grep) and update each to pass `profile=portfolio.profile`. If any caller doesn't have the portfolio loaded, load it. Failing to thread the profile through means new portfolios silently fall back to 0.05 — defeats the PR.

### 3. Backfill migration

New migration `backend/alembic/versions/0143_cvar_profile_defaults.py`. Verify next migration number with `ls backend/alembic/versions/ | sort | tail -3` — head was `0142_construction_cascade_telemetry` post-PR-A11; A12 added none, A12.1 adds none. So 0143 is correct unless A12.1 added one (unlikely per its spec).

Migration content:

```python
"""PR-A12.2: profile-differentiated CVaR defaults backfill.

Updates existing portfolio_calibration rows to use the institutional
starting defaults per profile (Conservative 2.5%, Moderate 5%, Growth 8%,
Aggressive 10%). Only updates rows that still hold the legacy uniform
5% default — operator-customized values (anything other than 0.0500)
are preserved.
"""
from alembic import op


revision = "0143_cvar_profile_defaults"
down_revision = "0142_construction_cascade_telemetry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE portfolio_calibration pc
        SET cvar_limit = CASE mp.profile
            WHEN 'conservative' THEN 0.0250
            WHEN 'moderate'     THEN 0.0500
            WHEN 'growth'       THEN 0.0800
            WHEN 'aggressive'   THEN 0.1000
            ELSE pc.cvar_limit
        END
        FROM model_portfolios mp
        WHERE pc.portfolio_id = mp.id
          AND pc.cvar_limit = 0.0500;
    """)


def downgrade() -> None:
    # Reverse: restore uniform 5% on the rows we touched.
    op.execute("""
        UPDATE portfolio_calibration pc
        SET cvar_limit = 0.0500
        FROM model_portfolios mp
        WHERE pc.portfolio_id = mp.id
          AND mp.profile IN ('conservative', 'growth', 'aggressive');
    """)
```

**Critical safety:** the `WHERE pc.cvar_limit = 0.0500` filter means operator-customized values (anything else) are preserved. If an operator has already set Conservative to 3% manually, the migration won't touch it. Decimal equality works because the column is Numeric(6,4) — `0.0500` is exact.

The downgrade is best-effort — it can't distinguish between "we set it" and "operator set it back to 5%". Acceptable for this kind of cosmetic data backfill.

**No schema change** — only data UPDATE. Server default in the column definition (migration 0100) stays at whatever it was — the helper function in code is now the authoritative default for new rows.

### 4. Tests

New file `backend/tests/wealth/test_cvar_profile_defaults.py`:

```python
"""PR-A12.2 — verify profile-differentiated CVaR defaults."""
from decimal import Decimal

from app.domains.wealth.models.model_portfolio import default_cvar_limit_for_profile


def test_conservative_default():
    assert default_cvar_limit_for_profile("conservative") == Decimal("0.0250")


def test_moderate_default():
    assert default_cvar_limit_for_profile("moderate") == Decimal("0.0500")


def test_growth_default():
    assert default_cvar_limit_for_profile("growth") == Decimal("0.0800")


def test_aggressive_default():
    assert default_cvar_limit_for_profile("aggressive") == Decimal("0.1000")


def test_unknown_profile_falls_back_to_moderate():
    assert default_cvar_limit_for_profile("custom_profile") == Decimal("0.0500")


def test_none_profile_falls_back_to_moderate():
    assert default_cvar_limit_for_profile(None) == Decimal("0.0500")


def test_case_insensitive():
    assert default_cvar_limit_for_profile("CONSERVATIVE") == Decimal("0.0250")
```

Add an integration test (in the same file or `test_model_portfolios.py` if it exists) that creates a portfolio with `profile="conservative"` via the API and asserts the auto-created calibration has `cvar_limit == Decimal("0.0250")`. Use the existing test fixtures.

---

## Verification

1. `make lint` — green
2. `make typecheck` — no new errors
3. `pytest backend/tests/wealth/test_cvar_profile_defaults.py -v` — all 7+ tests green
4. `pytest backend/tests/wealth/ backend/tests/quant_engine/ -q` — full sweep green, no regressions
5. **Live DB migration:**
   ```bash
   cd backend && alembic upgrade head
   ```
   Then verify:
   ```python
   # python -X utf8
   import psycopg
   with psycopg.connect("postgresql://netz:netz@localhost:5434/netz_engine") as conn, conn.cursor() as cur:
       cur.execute("""
           SELECT mp.profile, mp.display_name, pc.cvar_limit
           FROM portfolio_calibration pc
           JOIN model_portfolios mp ON mp.id = pc.portfolio_id
           WHERE mp.id IN (
               '3945cee6-f85d-4903-a2dd-cf6a51e1c6a5',
               'e5892474-7438-4ac5-85da-217abcf99932',
               '3163d72b-3f8c-427e-9cd2-bead6377b59c'
           )
           ORDER BY mp.profile
       """)
       for r in cur.fetchall(): print(r)
   ```
   **Expected post-migration:**
   - `('conservative', 'Conservative Preservation', Decimal('0.0250'))`
   - `('growth', 'Dynamic Growth', Decimal('0.0800'))`
   - `('moderate', 'Balanced Income', Decimal('0.0500'))`

6. **Live DB smoke (regression check):** trigger a build for Conservative Preservation. Conservative now has CVaR limit 2.5% — well above the universe floor (≈0.42% per A12 smoke). Phase 1 should still succeed. Expected: `cascade_summary="phase_1_succeeded"`, status=succeeded, `achievable_return_band` populated with `upper_at_cvar` close to 2.5% (vs ~1.92% pre-A12.2 with 5% limit). The band's `upper` (max return at limit) will be lower than pre-A12.2 because the tighter constraint binds — that's the point.

   If Conservative degrades to `phase_3_min_cvar_above_limit` post-A12.2, that means 2.5% is below the universe floor for Conservative's strategic allocation today. Either (a) accept and signal in PR-A13 ("your starting default is below the achievable floor"), or (b) raise the default to 3.0%. Decide empirically — do not blindly defend 2.5% if the data says no.

---

## Pass criteria summary

| # | Criterion | How verified |
|---|---|---|
| 1 | Helper function exists and returns correct Decimals | unit tests |
| 2 | Both creation sites (`create_portfolio`, `_ensure_calibration`) thread profile → default | manual code review + integration test |
| 3 | Migration 0143 backfills only rows with cvar_limit=0.05 | SQL verification post-upgrade |
| 4 | Operator-customized values (≠0.05) preserved | spot-check via SQL — find any non-0.05 row pre-migration, confirm unchanged post-migration (likely none in dev) |
| 5 | Existing tests green | full sweep |
| 6 | Conservative still hits Phase 1 with new 2.5% limit | live smoke |

---

## Commit & PR

**Branch:** `feat/pr-a12-2-cvar-profile-defaults`

**Commit message:**

```
feat(wealth): profile-differentiated CVaR defaults (PR-A12.2)

Pre-A12.2 all 3 canonical model_portfolios shared cvar_limit=5% — the
differentiator was only strategic_allocation block weights. Conservative
should expect tail-loss containment around 2.5%; Growth accepts up to 8%.
Uniform 5% defeated the operator's mandate intent.

Add default_cvar_limit_for_profile() helper as the single source of truth.
Wire both calibration creation sites (create_portfolio + _ensure_calibration)
to use it. Backfill migration 0143 updates only rows still at the legacy
5% default — operator-customized values are preserved.

Defaults are starting points the operator overrides via the Builder slider
(PR-A13). Out-of-scope: changing the migration 0100 server default;
operator UI for editing the per-profile defaults org-wide.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

**PR title:** `feat(wealth): profile-differentiated CVaR defaults (PR-A12.2)`

**PR body:** include the verification SQL output + the post-migration smoke result for Conservative.

---

## Out of scope

- Frontend Builder slider (PR-A13) — A12.2 is the upstream defaults that A13 consumes
- Org-level admin UI for editing the per-profile default mapping (different config layer; future)
- Changing `cvar_level` (always 0.95 — academic standard)
- Touching `lambda_risk_aversion`, `max_single_fund_weight`, `turnover_cap` defaults (separate concern; this PR is CVaR-only)
- μ prior calibration (`memory/project_mu_prior_calibration_concern.md` — separate sprint)
- Changing the migration 0100 server-side `cvar_limit` DEFAULT clause (the helper in code is now authoritative; the server default stays as 0.05 fallback for any insert path that bypasses both creation helpers)
- Adding new profiles (e.g., "income", "esg") — those would need their own block allocations first

---

**End of spec. If post-migration smoke shows Conservative degrades to phase_3_min_cvar_above_limit at 2.5%, do NOT commit blindly — flag and propose 3.0% as alternative; let consultant verify before merge.**
