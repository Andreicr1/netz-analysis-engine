# Macro Desk Redesign — Unified Regime + High-End Terminal Layout

**Date:** 2026-04-14
**Branch:** `feat/macro-desk-redesign`
**Sessions:** 2 (Session A: Backend structured signals, Session B: Frontend redesign)
**Depends on:** main (regime unification #161 + dynamic weights #164 merged)

---

## Problem

The Macro Desk still shows 4 regional regime tiles with "EXPANSION" badges from the killed primitive classifier. The signal breakdown dumps raw strings. The stress score is buried in a small span. No CTA to advance to allocation. The layout is a collection of generic cards, not an institutional command center.

---

## Session A — Backend: Structured Signal Breakdown

### OBJECTIVE

1. Add structured `signal_breakdown` field to `GlobalRegimeRead` and persist in `MacroRegimeSnapshot`.
2. Add 4 FRED series to the allowlist for sparklines.
3. Return `classify_regime_multi_signal` structured data alongside existing `reasons` dict.

### DELIVERABLES

#### 1. New schema: `RegimeSignalRead`

File: `backend/app/domains/wealth/schemas/allocation.py`

Add before `GlobalRegimeRead`:

```python
class RegimeSignalRead(BaseModel):
    """Structured breakdown of a single regime signal."""
    key: str               # "vix", "hy_oas", "cfnai", etc.
    label: str             # "VIX", "Credit Spread", "Activity Index", etc.
    raw_value: float | None  # 19.5, 2.90, -0.11
    unit: str              # "", "%", "σ", "/100"
    stress_score: float    # 0-100 per-signal stress
    weight_base: float     # base weight before amplification
    weight_effective: float  # weight after dynamic amplification
    category: str          # "financial" or "real_economy"
    fred_series: str | None = None  # FRED series ID for sparkline linkage
```

Signal key to metadata mapping (define as a dict constant in regime_service.py or the schema file):

```python
SIGNAL_METADATA: dict[str, dict] = {
    "vix":           {"label": "VIX",             "unit": "",     "category": "financial",    "fred_series": "VIXCLS"},
    "hy_oas":        {"label": "Credit Spread",   "unit": "%",    "category": "financial",    "fred_series": "BAMLH0A0HYM2"},
    "energy_shock":  {"label": "Energy Shock",    "unit": "/100", "category": "financial",    "fred_series": "DCOILWTICO"},
    "dxy":           {"label": "USD Strength",    "unit": "σ",    "category": "financial",    "fred_series": "DTWEXBGS"},
    "yield_curve":   {"label": "Yield Curve",     "unit": "%",    "category": "financial",    "fred_series": "DGS10"},
    "baa_spread":    {"label": "Corp. Stress",    "unit": "%",    "category": "financial",    "fred_series": "BAA10Y"},
    "cfnai":         {"label": "Activity Index",  "unit": "",     "category": "real_economy", "fred_series": "CFNAI"},
    "sahm":          {"label": "Employment",      "unit": "",     "category": "real_economy", "fred_series": "SAHMREALTIME"},
    "ff_roc":        {"label": "Fed Policy",      "unit": "%",    "category": "real_economy", "fred_series": "DFF"},
    "icsa":          {"label": "Jobless Claims",  "unit": "σ",    "category": "real_economy", "fred_series": "ICSA"},
    "credit_impulse":{"label": "Credit Impulse",  "unit": "%",    "category": "real_economy", "fred_series": "TOTBKCR"},
    "permits":       {"label": "Building Permits","unit": "%",    "category": "real_economy", "fred_series": "PERMIT"},
}
```

#### 2. Modify `classify_regime_multi_signal` to return structured signals

File: `backend/quant_engine/regime_service.py`

Currently the function returns `tuple[str, dict[str, str]]` (regime, reasons).

Change return type to `tuple[str, dict[str, str], list[dict]]` — add a third element: the structured signals list.

The function already builds `signals: list[tuple[str, float, float, str]]` internally (label, sub_score, weight, reason_str). After the dynamic weight amplification, also build a structured list:

```python
structured_signals = []
for label, sub_score, weight, reason_str in signals:
    meta = SIGNAL_METADATA.get(label, {})
    # Extract raw_value from reason_str if possible, or pass None
    structured_signals.append({
        "key": label,
        "label": meta.get("label", label),
        "raw_value": _extract_raw_value(reason_str),  # helper to parse "VIX=19.5" -> 19.5
        "unit": meta.get("unit", ""),
        "stress_score": round(sub_score, 1),
        "weight_base": round(base_weights.get(label, weight), 4),
        "weight_effective": round(weight, 4),  # after amplification
        "category": meta.get("category", "financial"),
        "fred_series": meta.get("fred_series"),
    })
```

Add helper `_extract_raw_value(reason_str: str) -> float | None` that parses the first number from strings like "VIX=19.5 (stress=...)".

Return: `return regime, reasons, structured_signals`

**Backward compatibility:** All existing callers destructure `regime, reasons = classify_regime_multi_signal(...)`. They will need to be updated to `regime, reasons, _ = ...` or `regime, reasons, signals = ...`. Check all callers:
- `get_current_regime()` in regime_service.py
- `run_global_regime_detection()` in risk_calc.py
- `_compute_and_persist_taa_state()` in risk_calc.py
- Any test files

#### 3. Persist `signal_breakdown` on `MacroRegimeSnapshot`

File: `backend/app/domains/wealth/models/allocation.py`

Add column:
```python
signal_breakdown: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)
```

**Migration:** Create a new Alembic migration adding `signal_breakdown JSONB` column to `macro_regime_snapshot` table. Nullable, no default needed.

File: `backend/app/domains/wealth/workers/risk_calc.py`

In `run_global_regime_detection()` (line ~1176), after `regime, reasons = classify_regime_multi_signal(**inputs)`, capture the structured signals:

```python
regime, reasons, structured_signals = classify_regime_multi_signal(**inputs)
```

Add `signal_breakdown=structured_signals` to the upsert values dict.

#### 4. Extend `GlobalRegimeRead` schema

File: `backend/app/domains/wealth/schemas/allocation.py`

Add field:
```python
class GlobalRegimeRead(BaseModel):
    as_of_date: date
    raw_regime: str
    stress_score: float
    signal_details: dict[str, str] = {}
    signal_breakdown: list[RegimeSignalRead] = []  # NEW

    @model_validator(mode="after")
    def _humanize(self) -> "GlobalRegimeRead":
        object.__setattr__(self, "raw_regime", humanize_regime(self.raw_regime))
        return self
```

#### 5. Update route handlers to include `signal_breakdown`

Files: `backend/app/domains/wealth/routes/macro.py` and `allocation.py`

Both `GET /macro/regime` and `GET /allocation/regime` read from `MacroRegimeSnapshot`. Add `signal_breakdown` to the response construction:

```python
return GlobalRegimeRead(
    as_of_date=snapshot.as_of_date,
    raw_regime=snapshot.raw_regime,
    stress_score=snapshot.stress_score,
    signal_details=snapshot.signal_details,
    signal_breakdown=snapshot.signal_breakdown or [],
)
```

#### 6. Add FRED series to allowlist

File: `backend/app/domains/wealth/routes/macro.py`

Add to `_FRED_ALLOWLIST` (around line 873):
```python
"CFNAI",
"SAHMREALTIME",
"ICSA",
"TOTBKCR",
```

### VERIFICATION

1. `make test` passes.
2. `make typecheck` passes.
3. `make migration MSG="add signal_breakdown to macro_regime_snapshot"` creates clean migration.
4. `make migrate` applies without error.
5. After running regime detection worker, `GET /macro/regime` returns `signal_breakdown` as a list of structured objects.
6. `GET /macro/fred?series_id=CFNAI` returns data (after macro_ingestion has run).

---

## Session B — Frontend: Terminal Command Center Layout

### CONTEXT

Session A delivered structured `signal_breakdown` on `GET /macro/regime`. The response now includes:
```typescript
interface RegimeSignalRead {
    key: string;
    label: string;
    raw_value: number | null;
    unit: string;
    stress_score: number;
    weight_base: number;
    weight_effective: number;
    category: "financial" | "real_economy";
    fred_series: string | null;
}

interface GlobalRegimeRead {
    as_of_date: string;
    raw_regime: string;       // "Expansion" | "Cautious" | "Stress"
    stress_score: number;     // 0-100
    signal_details: Record<string, string>;  // legacy, keep for compat
    signal_breakdown: RegimeSignalRead[];    // NEW structured data
}
```

### OBJECTIVE

Redesign `(terminal)/macro/+page.svelte` with a new layout:

```
+==================================================================+
|  STRESS HERO (full-width, ~80px)                                 |
|  Score: 31   CAUTIOUS   ════████░░░░░░░░░░░░░░░░░░░░░░░░  /100  |
|  Financial 40% eff→52%   Real Economy 60% eff→48%                |
|  [PIN REGIME]                           [PROCEED TO ALLOC ->]    |
+==================================================================+
|  SIGNAL BREAKDOWN (2-column, ~300px)                             |
|  FINANCIAL SIGNALS          |  REAL ECONOMY SIGNALS              |
|  VIX         19.5    9/100  |  Activity    -0.11    0/100        |
|  ▓░░░░░░░░░  0.10→0.07     |  ░░░░░░░░░░  0.18→0.12            |
|  Credit Sp.  2.90%  11/100  |  Employment  0.20   40/100        |
|  ...                        |  ...                               |
+==================================================================+
|  REGIONAL HEALTH (5fr) | INDICATORS (4fr) | COMMITTEE (3fr)      |
|  US EU JP EM           | GDP CPI URate    | Apr 2  [APPROVED]    |
|  72 58 61 47           | sparklines       | Apr 1  [PENDING]     |
|  dimension bars        | sparklines       | ...                  |
+==================================================================+
```

### CONSTRAINTS

- All colors via `--terminal-*` CSS custom properties. No hex.
- Font: `var(--terminal-font-mono)`. No Urbanist.
- Border radius: 0.
- Formatters from `@netz/ui` exclusively.
- No localStorage. Module-level `$state` for pinned regime.
- Svelte 5 runes with `$derived` for computed values.
- `$effect` with `AbortController` — propagate signal to all fetch calls, cleanup on unmount.
- Smart backend, dumb frontend: show "Credit Spread" not "hy_oas", show "Activity Index" not "cfnai".
- LayoutCage pattern: `calc(100vh - 88px)`.

### DELIVERABLES

#### 1. Create `frontends/wealth/src/lib/components/terminal/macro/StressHero.svelte`

Full-width horizontal strip. The page's visual anchor.

Props:
```typescript
interface StressHeroProps {
    stressScore: number;        // 0-100
    regimeLabel: string;        // "Expansion" | "Cautious" | "Stress"
    asOfDate: string;
    financialEffWeight: number;
    realEconEffWeight: number;
    isPinned: boolean;
    onPin: () => void;
    onUnpin: () => void;
    onProceedToAlloc: () => void;
}
```

Visual spec:
- Score rendered large (32px+), `font-variant-numeric: tabular-nums`, color-coded: green (<33), amber (33-66), red (>66).
- Regime label same size, uppercase, `--terminal-fg-primary`.
- Horizontal bar: `height: 6px`, full width, background `--terminal-fg-muted`. Fill color matches score zone. Tick marks at 33% and 66%.
- Below bar: "FINANCIAL {base}% eff→{eff}%" and "REAL ECONOMY {base}% eff→{eff}%" showing dynamic weight redistribution.
- Two buttons: `[PIN REGIME]` / `[UNPIN]` (left) and `[PROCEED TO ALLOC ->]` (right).
- `as_of_date` displayed subtly: "as of 14 Apr 2026".

Color function (use across all components):
```typescript
function stressColor(score: number): string {
    if (score < 33) return "var(--terminal-status-ok)";
    if (score < 66) return "var(--terminal-accent-amber)";
    return "var(--terminal-status-error)";
}
```

#### 2. Create `frontends/wealth/src/lib/components/terminal/macro/SignalBreakdown.svelte`

Two-column signal panel. Left: financial signals. Right: real economy signals.

Props:
```typescript
interface SignalBreakdownProps {
    signals: RegimeSignalRead[];
}
```

Each signal row renders:
```
  LABEL          VALUE     STRESS/100
  ████░░░░░░░░░  w: 0.12 → 0.26
```

- Label: uppercase, 120px fixed width, `--terminal-fg-secondary`.
- Value: right-aligned, tabular-nums. Append unit from signal data.
- Stress: color-coded (green/amber/red at 33/66 thresholds). Format: "{stress}/100".
- Bar: `height: 4px`, fill proportional to `stress_score / 100`, same color.
- Weight line: `--terminal-fg-muted`. When `weight_effective > weight_base * 1.2`, arrow + wEff in `--terminal-accent-amber` (amplification highlight). When `< 0.8`, use `--terminal-fg-muted` (attenuation).

Column headers: "FINANCIAL SIGNALS ({n})" and "REAL ECONOMY SIGNALS ({n})".

Sorting: within each column, sort by `weight_effective` descending (highest driver on top).

Use `formatNumber` from `@netz/ui` for all numeric display.

#### 3. Rename `RegimeTile.svelte` to `RegionalHealthTile.svelte`

File: rename `frontends/wealth/src/lib/components/terminal/macro/RegimeTile.svelte` to `RegionalHealthTile.svelte`.

Changes:
- Remove `regime` prop entirely. No regime badge.
- Remove `REGIME_COLORS` constant.
- Remove regime badge rendering.
- Keep composite score display and dimension bars.
- Rename component.

Props:
```typescript
interface RegionalHealthTileProps {
    region: string;
    compositeScore: number;
    dimensions: Array<{ name: string; score: number }>;
}
```

#### 4. Rewrite `frontends/wealth/src/routes/(terminal)/macro/+page.svelte`

**DELETE:**
- `REGIME_DISPLAY` map and `sanitizeRegime()` function (dead code — backend humanizes).
- The `globalRegimeLabel` derived that uses `sanitizeRegime`.
- The tile assembly logic that reads `regime.regional_regimes[key]`.
- Import of `RegimeTile`.
- The signal chips section that dumps raw `signal_details` strings.

**NEW LAYOUT:**
```svelte
<div class="macro-desk" style="height: calc(100vh - 88px); overflow-y: auto; padding: 24px;">
    <StressHero ... />
    <SignalBreakdown signals={regime?.signal_breakdown ?? []} />
    <div class="macro-bottom">
        <Panel><PanelHeader title="REGIONAL ECONOMIC HEALTH" />
            <div class="region-grid">
                {#each tiles as tile (tile.region)}
                    <RegionalHealthTile {...tile} />
                {/each}
            </div>
        </Panel>
        <Panel><PanelHeader title="MACRO INDICATORS" />
            <SparklineWall indicators={sparklineData} />
        </Panel>
        <Panel><PanelHeader title="COMMITTEE REVIEWS" />
            <CommitteeReviewFeed reviews={reviewCards} />
        </Panel>
    </div>
</div>
```

Bottom grid: `grid-template-columns: 5fr 4fr 3fr`.

**DATA FETCHING with AbortController:**
```typescript
$effect(() => {
    const ac = new AbortController();

    fetchAllData(ac.signal);
    const timer = setInterval(() => fetchAllData(ac.signal), 5 * 60 * 1000);

    return () => {
        ac.abort();
        clearInterval(timer);
    };
});
```

**DERIVED STATE:**
```typescript
const financialSignals = $derived(
    (regime?.signal_breakdown ?? [])
        .filter(s => s.category === "financial")
        .sort((a, b) => b.weight_effective - a.weight_effective)
);

const realEconSignals = $derived(
    (regime?.signal_breakdown ?? [])
        .filter(s => s.category === "real_economy")
        .sort((a, b) => b.weight_effective - a.weight_effective)
);

const financialEffWeight = $derived(
    financialSignals.reduce((sum, s) => sum + s.weight_effective, 0)
);

const realEconEffWeight = $derived(
    realEconSignals.reduce((sum, s) => sum + s.weight_effective, 0)
);
```

**TILES (regional health, no regime):**
```typescript
const tiles = $derived.by(() => {
    if (!scores) return [];
    return REGION_ORDER.map((key) => {
        const reg = scores.regions[key];
        if (!reg) return null;
        return {
            region: REGION_LABELS[key] ?? key,
            compositeScore: reg.composite_score,
            dimensions: Object.entries(reg.dimensions).map(([name, d]) => ({
                name,
                score: d.score,
            })),
        };
    }).filter(Boolean);
});
```

**PIN REGIME fix:**
```typescript
function handlePinRegime() {
    if (!regime) return;
    pinnedRegime.pin({
        label: regime.raw_regime,
        region: "GLOBAL",
        score: Math.round(regime.stress_score),
    });
}
```

#### 5. Delete `RegimeTile.svelte`

After renaming to `RegionalHealthTile.svelte`, delete the old file if it still exists.

### VERIFICATION

1. `pnpm --filter @investintell/wealth check` passes (0 errors).
2. Macro Desk shows stress score as hero element with horizontal bar.
3. Signal breakdown shows 2 columns with real signal data from `signal_breakdown`.
4. Dynamic weight amplification visible (base → effective weight with amber highlight when amplified).
5. Regional tiles show composite scores WITHOUT regime badges.
6. PIN REGIME pins global stress score (not regional average).
7. PROCEED TO ALLOC navigates to `/terminal/allocation`.
8. No hex colors, no Urbanist font, no shadcn imports.
9. `REGIME_DISPLAY` and `sanitizeRegime` removed.
10. AbortController cleans up on unmount.

### ANTI-PATTERNS

- Do NOT use a radial gauge for stress score. Terminal aesthetic is horizontal/linear.
- Do NOT parse `signal_details` strings with regex. Use the structured `signal_breakdown` field.
- Do NOT show regime badges on regional tiles. Regional regime is dead.
- Do NOT keep `sanitizeRegime()`. Backend already humanizes.
- Do NOT use `Math.round()` inline. Use `formatNumber` from `@netz/ui`.
- Do NOT import from shadcn or `@investintell/ui/components`. Terminal-native only.
