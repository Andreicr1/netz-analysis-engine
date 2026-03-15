---
date: 2026-03-14
topic: customizable-vertical-config
origin: Collaborative brainstorm session (Sprint 2 complete, planning Sprint 3+)
---

# Customizable Vertical Configuration System

## Context

The Netz Analysis Engine has vertical engines (`vertical_engines/`) that specialize analysis by asset class (private credit, liquid funds, venture capital, etc.). Currently, two separate config systems exist:

- `calibration/` (4 YAMLs) — feeds `quant_engine/` with CVaR limits, regime thresholds, portfolio profiles, scoring weights. **Wealth-only, created for the old Wealth OS.**
- `profiles/` (1 YAML) — feeds `ai_engine/` with IC memo chapter definitions, token budgets.

Both are global/shared — no per-vertical or per-tenant customization. This is architecturally wrong for a multi-vertical, multi-tenant B2B SaaS product.

## What We're Building

A unified **ProductConfig** system that makes the entire analysis experience customizable per vertical AND per tenant. The configuration IS the product differentiator.

**Four pillars of customization:**

| Pillar | What it controls | Who edits | Example |
|---|---|---|---|
| **Calibration** | Quantitative thresholds, limits, risk parameters | **Client** (self-service within guardrails) | Credit: LTV < 65%, DSCR > 1.25x. Wealth: CVaR 95% < -5% |
| **Chapters** | Analysis structure — add, remove, reorder chapters | **Netz team** (per client request) | Client A wants 15 chapters (adds ESG). Client B wants 12. |
| **Prompts** | Tone, emphasis, analytical depth per chapter | **Netz prompt engineers** (IP — never visible to client) | Covenant analysis emphasis, sponsor track record depth. |
| **Model routing** | Which LLM for which analysis stage | **Netz team** (per vertical) | Credit uses Claude (legal analysis). Wealth uses GPT-4o (numeric). |

**Access model:**
- **Client self-service:** Calibration only (within guardrails defined by Netz).
- **Netz team:** Chapters, model routing, calibration defaults and guardrails.
- **Netz prompt engineers:** Prompts. These are proprietary IP — never exposed to clients.
- Clients do NOT touch code. They pass demands, Netz adjusts.

## Why This Approach

### Approaches Considered

**Approach A (CHOSEN): Config unificada no banco**
- Single `vertical_configs` table with JSONB
- Cascade: tenant override → vertical default → global fallback
- ConfigService with Redis cache
- YAML = seed data only (initial migration)
- Admin API + guardrails for client self-service

**Approach B (Rejected): Hybrid YAML + DB**
- YAML = defaults versionados no repo. DB = tenant overrides only.
- Rejected because: defaults require deploy to change, two systems to maintain, prompts on filesystem awkward for tenant overrides.

**Approach C (Rejected): Profiles as Product (fork/merge)**
- Full versioning, fork/merge workflow for configs.
- Rejected because: over-engineering for current stage. Fork/merge of configs is hard. Can evolve to this later if needed.

### Why Approach A

1. **Single source of truth** — one table, one service, one cache pattern.
2. **Instant changes** — no deploy needed to adjust calibration for a client.
3. **Guardrails native** — `guardrails JSONB` column defines allowed ranges per config.
4. **Audit trail** — `created_by`, `updated_by`, timestamps on every config change.
5. **Multi-vertical from day one** — each vertical has its own config types with appropriate defaults.
6. **Scale** — same pattern works for 1 client (Netz) or 100.

## Key Decisions

### D1: All config in the database, YAML = seed only

Current YAML files in `calibration/` and `profiles/` become seed data. A migration loads them into `vertical_configs` table. Services never read YAML directly — they go through `ConfigService` which queries DB with Redis cache.

**Rationale:** Client demands adjustment → Netz team changes via API → instant effect. No PR, no deploy, no waiting.

### D2: Cascade resolution order

```
ConfigService.get(vertical, config_type, org_id):
  1. DB: WHERE organization_id = org_id AND vertical = V AND config_type = T
  2. DB: WHERE organization_id IS NULL AND vertical = V AND config_type = T
  3. Seed YAML fallback (emergency only — should never happen in production)
```

This means: tenant override wins. If no tenant override exists, vertical default applies. If vertical default somehow missing from DB, YAML fallback prevents crash.

### D3: Client self-service with guardrails — calibration only

Clients can edit **calibration** within ranges defined by Netz. Example:
- Netz sets guardrail: `cvar_limit: {min: -15.0, max: -3.0}`
- Client A sets `cvar_limit: -8.0` ✅
- Client B tries `cvar_limit: -1.0` ❌ rejected (outside guardrail)

**Clients CANNOT access:** prompts (proprietary IP), model routing, or chapter templates. These are managed exclusively by Netz team.

Guardrails are stored alongside the default config in the `vertical_config_defaults` table. Only `config_type = 'calibration'`, `'scoring'`, and `'blocks'` have guardrails — other config types have `guardrails = NULL` (not client-editable).

### D4: Each vertical defines its own calibration schema

Credit calibration looks fundamentally different from wealth calibration:

| Wealth calibration | Credit calibration |
|---|---|
| CVaR limits per risk profile | LTV thresholds per structure type |
| Regime thresholds (VIX, yield curve) | DSCR/ICR minimums |
| Portfolio allocation targets | Concentration limits (sector, geography) |
| Fund scoring weights | Deal scoring weights (sponsor, structure, terms) |
| Drift bands (DTW) | Covenant severity weights |

The JSONB approach handles this naturally — each vertical's config has a different schema, validated by the vertical engine, not by the table.

### D5: Prompts are Netz IP — stored in DB, never exposed to clients

Prompts are Jinja2 templates stored in `vertical_config_defaults` with `config_type = 'prompts'`. The JSONB contains `{chapter_id: template_text}`. Managed exclusively by Netz prompt engineers via internal admin tools.

**Why in DB (not filesystem):**
- Per-vertical prompt sets (credit prompts ≠ wealth prompts) managed centrally.
- Netz prompt engineer can iterate without deploy cycles.
- Prompt versions tracked via audit table.

**Never exposed to clients:** Prompts contain the analytical methodology and reasoning patterns that constitute Netz's core IP. The client sees the output (IC memo), never the prompt. No API endpoint returns prompt content to non-Netz roles.

**Team plan:** A dedicated prompt engineer will own prompt quality, A/B testing, and per-vertical optimization. The DB-backed system supports this workflow natively.

### D6: Phased implementation across sprints

| Sprint | What | Why |
|---|---|---|
| Sprint 3 | `vertical_configs` table + `ConfigService` + seed migration + Redis cache | Vertical engines need config from day one. Avoid retrabalho. |
| Sprint 5-6 | Admin API endpoints (Netz super-admin CRUD) | Frontends exist, can build admin panel. |
| Sprint 7+ | Client-facing calibration UI with guardrails | Wealth frontend exists, self-service UX. |

### D7: calibration/ directory becomes seed-only

The `calibration/config/` directory stays in the repo as seed data and documentation, but is never read at runtime. The seed migration (`0004_vertical_configs.py`) loads these YAMLs into the database. Future calibration changes go through the API, not YAML edits.

### D8: profiles/ merges conceptually with calibration

There is no longer a distinction between "AI config" and "quant config". Everything is a `config_type` in `vertical_configs`:

| config_type | What it contains |
|---|---|
| `calibration` | Quantitative thresholds (CVaR, LTV, DSCR, drift, regime) |
| `chapters` | Chapter definitions (id, title, type, max_tokens, chunk_budget) |
| `prompts` | Jinja2 templates per chapter |
| `model_routing` | LLM selection per analysis stage |
| `scoring` | Scoring weights for deals/funds |
| `blocks` | Allocation blocks / sector-geography taxonomy |
| `tone` | Tone normalization parameters |
| `evaluation` | Evaluation criteria and quality thresholds |

## Table Schema

```sql
-- Defaults: NO RLS, NO organization_id. Netz-managed. Visible to all tenants.
CREATE TABLE vertical_config_defaults (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vertical TEXT NOT NULL,
    config_type TEXT NOT NULL,
    config JSONB NOT NULL,
    guardrails JSONB,              -- allowed ranges for client self-service
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by TEXT,
    updated_by TEXT,
    UNIQUE (vertical, config_type)
);

-- Overrides: WITH RLS on organization_id. Tenant-specific. Defense in depth.
CREATE TABLE vertical_config_overrides (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    vertical TEXT NOT NULL,
    config_type TEXT NOT NULL,
    config JSONB NOT NULL,         -- sparse: only changed fields (deep-merged with default)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by TEXT,
    updated_by TEXT,
    UNIQUE (organization_id, vertical, config_type)
);

ALTER TABLE vertical_config_overrides ENABLE ROW LEVEL SECURITY;
ALTER TABLE vertical_config_overrides FORCE ROW LEVEL SECURITY;
CREATE POLICY org_isolation ON vertical_config_overrides
    USING (organization_id = (SELECT current_setting('app.current_organization_id')::uuid));

CREATE INDEX idx_config_overrides_lookup
    ON vertical_config_overrides (vertical, config_type, organization_id);

-- Audit trail: DB trigger captures every change automatically.
CREATE TABLE vertical_config_audit (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    table_name TEXT NOT NULL,      -- 'vertical_config_defaults' or 'vertical_config_overrides'
    record_id UUID NOT NULL,
    organization_id UUID,
    vertical TEXT NOT NULL,
    config_type TEXT NOT NULL,
    old_config JSONB,
    new_config JSONB NOT NULL,
    changed_by TEXT,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## ConfigService Interface

```python
class ConfigService:
    """
    Resolves configuration for a given vertical + config_type + optional org_id.
    Cascade: override (org-scoped, RLS) → default (global) → YAML seed fallback.
    Cache: Redis with 5min TTL, invalidated on write via pub/sub.
    """
    async def get(self, vertical: str, config_type: str, org_id: UUID | None = None) -> dict:
        """Returns deep_merge(default, override). Override wins on conflicts."""
        ...

    async def set_default(self, vertical: str, config_type: str, config: dict,
                          guardrails: dict | None = None, actor: str = None) -> None:
        """Netz super-admin sets vertical default. No org_id."""
        ...

    async def set_override(self, vertical: str, config_type: str, config: dict,
                           org_id: UUID, actor: str = None) -> None:
        """Set tenant-specific override. Validates against guardrails first."""
        ...

    async def validate_guardrails(self, vertical: str, config_type: str,
                                   proposed: dict, org_id: UUID) -> list[str]:
        """Returns list of violations. Empty list = valid."""
        ...

    async def get_with_guardrails(self, vertical: str, config_type: str,
                                   org_id: UUID) -> ConfigWithGuardrails:
        """Returns merged config + guardrail ranges for UI rendering."""
        ...

    async def list_configs(self, vertical: str, org_id: UUID | None = None) -> list[ConfigEntry]:
        """Lists all config_types for a vertical, with override status per org."""
        ...
```

## Impact on Existing Architecture

### What changes

| Component | Current | New |
|---|---|---|
| `calibration/config/*.yaml` | Runtime config source | Seed data only (loaded into DB by migration) |
| `profiles/*/profile.yaml` | Runtime config source | Seed data only |
| `quant_engine/*.py` services | `yaml.safe_load()` with `@lru_cache` | `ConfigService.get(vertical, config_type)` |
| `ai_engine/profile_loader.py` | Loads YAML from filesystem | Loads from `ConfigService` |
| `vertical_engines/*/` | Hardcoded defaults | Receives config via `ConfigService` injection |

### What stays the same

- `vertical_engines/` code structure (code is code, config is config)
- `ai_engine/` universal modules (extraction, governance, validation)
- `quant_engine/` service interfaces (only config loading changes)
- RLS, auth, tenancy middleware
- StorageClient, SSE, Redis patterns

## Credit Calibration — Per-Vertical Config Types

Each vertical defines its own calibration parameters appropriate to the asset class. These are NOT shared across verticals — a credit fund's risk parameters are fundamentally different from a liquid fund's.

### Private Credit calibration types (to be refined with best practices research):

| config_type | Parameters | Purpose |
|---|---|---|
| `calibration` | LTV thresholds by structure type, DSCR/ICR minimums, tenor limits, concentration limits (sector, geography, single-name) | Risk appetite boundaries |
| `scoring` | Deal scoring weights: sponsor quality, structure quality, covenant package, collateral coverage, market timing | Deal ranking and prioritization |
| `chapters` | 14 IC memo chapters (customizable: add ESG, remove peers, reorder) | Analysis structure |
| `prompts` | Per-chapter Jinja2 with emphasis on credit-specific analysis | Analysis tone and depth |
| `model_routing` | Claude for legal/covenant analysis, GPT-4o for financial modeling | LLM selection |

### Liquid Funds calibration types:

| config_type | Parameters | Purpose |
|---|---|---|
| `calibration` | CVaR limits per risk profile, regime thresholds (VIX, yield curve, CPI, Sahm), drift bands | Risk monitoring |
| `scoring` | Fund scoring weights: return consistency, risk-adjusted return, drawdown control, info ratio | Fund selection |
| `blocks` | Allocation blocks: geography × asset class → ETF proxy mapping | Investment universe |
| `profiles` | Portfolio model profiles (conservative/moderate/growth) with strategic allocation targets | Portfolio construction |
| `chapters` | 7 DD report chapters | Analysis structure |
| `prompts` | Per-chapter Jinja2 for wealth DD reports | Analysis tone |
| `model_routing` | GPT-4o for numeric analysis, Claude for qualitative | LLM selection |

## Commercial Differentiation

This architecture enables three tiers of commercial value:

1. **Standard** — Netz defaults per vertical. Client gets institutional-grade analysis out of the box. Prompts, models, chapters optimized by Netz team.
2. **Customized** — Netz adjusts chapters, prompts, model routing for the client's specific mandate. Calibration defaults tailored to their risk appetite. Delivered as professional service.
3. **Self-service calibration** — Client adjusts quantitative parameters (thresholds, limits, scoring weights) within guardrails. Real-time effect. No Netz involvement for routine calibration changes.

**IP protection model:** The analytical methodology (prompts, model routing, chapter logic) is Netz proprietary IP — never exposed to clients. What clients see is the output (IC memos, DD reports, risk metrics). What they can customize is the quantitative framework (calibration). This is analogous to Bloomberg Terminal: the methodology is opaque, but the parameters are configurable.

No competitor in the VDR / credit analysis space offers this combination of analytical depth AND calibration customizability. Most deliver generic analysis with no parameterization.

## Resolved Questions

### RQ1: RLS on config tables → Two tables for defense in depth

Tenant calibrations reveal sensitive information (risk appetite, internal limits, decision weights). A bug in application-level access control could leak configs between tenants. Solution:

- `vertical_config_defaults` — NO RLS, NO `organization_id`. Netz defaults visible to all. Same pattern as `macro_data`.
- `vertical_config_overrides` — RLS on `organization_id`. Impossible to leak between tenants even with application bugs.

`ConfigService` merges: `deep_merge(default, override)`, override wins on conflicts.

### RQ2: Config versioning → Audit table with DB trigger

Institutional clients need audit trail: "who changed the CVaR limit and when?" Solution:

- `vertical_config_audit` table with `old_config JSONB`, `new_config JSONB`, `changed_by TEXT`, `changed_at TIMESTAMPTZ`.
- DB trigger on `UPDATE` of both config tables captures diff automatically.
- No manual audit code needed — trigger handles everything.

### RQ3: Prompt customization → Internal only, template slots pattern

Prompts are Netz IP and never visible to clients. Internally, the Netz prompt engineer works with a **template + slots** pattern for maintainability:

```json
{
  "ch01_exec": {
    "emphasis": ["covenant_structure", "esg_compliance"],
    "tone": "conservative",
    "criteria": ["DSCR > 1.25x required", "LTV < 65% for senior secured"],
    "additional_instructions": "Focus on downside protection over upside potential"
  }
}
```

The base Jinja2 template reads slots via `{{ config.emphasis }}`, `{{ config.tone }}`. The calibration values (DSCR threshold, LTV limit) are injected from `ConfigService.get('calibration')` — so when a client changes their calibration, prompts automatically reflect those thresholds without the client ever seeing the prompt itself.

This separation means: **client edits calibration → prompts consume calibration values → analysis output reflects client preferences** — all without exposing IP.

## Private Credit Calibration — Best Practices Research

Research based on Moody's Annual Default Study, S&P Recovery Reports, Basel III/CRE IV, and public filings of Ares Capital, Blue Owl, HPS Investment Partners.

### Leverage Limits (by structure type)

| Structure | Max Total Leverage | Warning | Preferred Range |
|---|---|---|---|
| Senior Secured | 5.0x | 4.5x | 2.5x – 4.0x |
| Unitranche | 5.5x | 5.0x | 3.0x – 4.5x |
| Second Lien | 6.5x | 6.0x | 4.0x – 5.5x |

Reference: Moody's B2 median ~5.0x, S&P B median ~5.5x (2023-2025 vintage).

### Coverage Ratios

| Metric | Hard Floor | Warning | Comfortable | Strong |
|---|---|---|---|---|
| DSCR | 1.10x | 1.25x | 1.50x | 2.00x |
| Interest Coverage (ICR) | 1.50x | 1.75x | 2.50x | 4.00x |
| Fixed Charge Coverage | 1.00x | 1.15x | 1.30x | — |

### LTV Limits (by structure)

| Structure | Max Hard | Warning | Preferred Range |
|---|---|---|---|
| Senior Secured (EV basis) | 65% | 60% | 40% – 55% |
| Unitranche | 70% | 65% | 45% – 60% |
| Second Lien | 80% | 75% | 55% – 70% |
| Real Estate (CRE) | 75% | 70% | 50% – 65% |

TEV stress haircut: 25% for downside LTV calculation.

### Credit Deal Scoring Weights (equivalent of `scoring.yaml`)

| Factor | Weight | Description |
|---|---|---|
| Credit quality | 0.25 | DSCR, ICR, leverage, LTV composite |
| Return adequacy | 0.20 | Spread vs risk, risk-adjusted return |
| Structural protection | 0.15 | Covenants, security package, waterfall |
| Sponsor quality | 0.15 | Track record, AUM, default history |
| Business quality | 0.10 | Revenue stability, margin, sector |
| Documentation completeness | 0.10 | Evidence quality, data gaps |
| Liquidity profile | 0.05 | Tenor, prepayment, exit path |

### Portfolio Concentration Limits

| Limit Type | Max | Warning |
|---|---|---|
| Single obligor | 10% of NAV | 7.5% |
| Top 5 obligors | 40% | 35% |
| Single sector (GICS) | 25% | 20% |
| Single country (non-domicile) | 40% | 30% |
| Emerging markets | 15% | 10% |
| Second lien allocation | 20% | 15% |
| PIK positions | 15% | 10% |

### Credit Regime Signals (equivalent of wealth regime thresholds)

| Signal | Normal | Cautious | Stress | Crisis |
|---|---|---|---|---|
| HY OAS (bps) | < 350 | 350–500 | 500–700 | > 1000 |
| Lev Loan Spread (bps) | < 400 | 400–550 | 550–700 | > 700 |
| Default Rate (Moody's spec-grade) | < 2% | 2–4% | 4–6% | > 10% |
| CLO Issuance YoY change | — | -30% | -50% | — |

### Credit Regime Definitions

| Regime | Pipeline Adj | Spread Premium | Leverage Adj | Covenant Req |
|---|---|---|---|---|
| NORMAL | 0% | 0 bps | 0 | Any |
| CAUTIOUS | -20% | +50 bps | -0.5x | Any |
| STRESS | -50% | +150 bps | -1.0x | Full maintenance |
| CRISIS | -80% | +300 bps | -1.5x | Full maintenance |

### Scenario Calibration (replaces `_SCENARIO_PROXY` in `ic_quant_engine.py`)

| Parameter | Base | Downside | Severe | Tail (1-in-25y) |
|---|---|---|---|---|
| Default rate | 2% | 5% | 10% | 15% |
| Recovery rate (1st lien) | 67% | 50% | 35% | 25% |
| Revenue change | +3% | -10% | -25% | -40% |
| EBITDA margin Δ | 0 bps | -200 bps | -500 bps | -800 bps |
| Rate shock | 0 bps | +100 bps | +200 bps | -200 bps |

### Return Requirements (by strategy)

| Strategy | Min Spread (SOFR+) | Net IRR Target |
|---|---|---|
| Core Senior Secured | 450 bps | 8–12% |
| Unitranche | 550 bps | 10–14% |
| Second Lien | 750 bps | 12–16% |
| Venture Debt | 800 bps | 12–18% |
| Distressed | 1000 bps | 15–20% |

### Monitoring Triggers (extends existing `policy_loader.py`)

| Trigger | Warning | Critical |
|---|---|---|
| Leverage increase from underwriting | +0.5x | +1.0x |
| DSCR decline from underwriting | -0.15 | -0.30 |
| Revenue decline YoY | -10% | -20% |
| EBITDA decline YoY | -15% | -25% |
| Payment delay (days) | 15 | 30 (default event) |
| NAV mark-down | 5% | 15% |
| Covenant headroom | < 10% | < 5% |

### Rating Agency Anchors (Moody's 1983-2024 averages)

| Rating | Annual Default Rate | Recovery (1st Lien) |
|---|---|---|
| Ba | 1.10% | 67% |
| B (core private credit) | 3.50% | 67% |
| Caa | 10.50% | 55% |

Expected Loss calibration: Core senior secured = PD 2.0% × LGD 30% = **60 bps/year**.

## Next Steps

→ `/ce:plan` to design the implementation across Sprints 3-7.
→ Credit calibration research incorporated above — ready for seed YAML generation.
