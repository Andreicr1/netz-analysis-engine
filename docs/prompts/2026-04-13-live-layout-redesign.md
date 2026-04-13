# Live Workbench Layout Redesign

**Branch:** `feat/live-layout-redesign`  
**Base:** `fix/taa-regime-signals` (or `main` if merged)

## Problem

Visual validation of the Live Workbench (`/portfolio/live`) reveals layout imbalance:

1. **Bottom row is a 3-column sub-grid** with Summary+Drift (200px) | Holdings (1fr) | Alerts+TradeLog (260px) -- too crowded, four small panels stacked in the bottom corners while the Watchlist left column uses full viewport height for just a ticker list
2. **DriftMonitorPanel** as a standalone table is visually awkward in a 200px-wide column -- the 5-column table (Fund/Target/Actual/Drift/Status) is unreadable at that width
3. **REBALANCE button** appears in BOTH PortfolioSummary footer AND DriftMonitorPanel footer -- duplicate CTA
4. **Right column** (News+Macro) only spans top 2 rows, leaving the bottom-right for Alerts+TradeLog which are contextually misplaced (alerts belong near watchlist/portfolio info, not next to news)

## Target Layout

Three-column grid, ALL columns spanning full height:

```
+--------------------+----------------------------------+--------------------+
| PORTFOLIO SELECTOR |          CHART TOOLBAR           |                    |
|  (in watchlist)    |                                  |                    |
+--------------------+----------------------------------+    NEWS FEED       |
|                    |                                  |    (flex: 55)      |
|    WATCHLIST       |          PRICE CHART             |                    |
|    (flex: 60)      |          (hero area)             |                    |
|                    |                                  +--------------------+
|                    |                                  |                    |
+--------------------+----------------------------------+  MARKET CONDITIONS |
|                    |                                  |    (flex: 45)      |
|    ALERTS          |     PORTFOLIO SUMMARY            |                    |
|    (flex: 25)      |     + HOLDINGS TABLE             |                    |
|                    |     (bottom band)                |                    |
+--------------------+                                  +--------------------+
|    TRADE LOG       |                                  |
|    (flex: 15)      |                                  |
+--------------------+----------------------------------+
```

- **Left column (220px):** Watchlist (top ~60%) + Alerts (middle ~25%) + Trade Log (bottom ~15%)
- **Center column (1fr):** Chart toolbar + Chart (top) + Portfolio Summary + Holdings (bottom)
- **Right column (280px):** News Feed (55%) + Market Conditions (45%) -- unchanged from current
- **DriftMonitorPanel:** REMOVED from layout. Drift breaches are injected as alert items into AlertStreamPanel
- **REBALANCE button:** Only in PortfolioSummary, properly integrated (not duplicated)

---

## File-by-File Changes

### 1. `frontends/wealth/src/routes/(terminal)/portfolio/live/+page.svelte`

This is the main layout file. The grid structure needs a complete rewrite.

#### 1a. Remove DriftMonitorPanel import (line 38)

Delete this line:
```
import DriftMonitorPanel from "$lib/components/terminal/live/DriftMonitorPanel.svelte";
```

#### 1b. Remove drift-related computed state that was ONLY used by DriftMonitorPanel

The following computed values at lines 449-469 (`isFallbackHoldings` and `driftFunds`) are used ONLY by DriftMonitorPanel. Remove them:

```typescript
// DELETE lines 449-469:
const isFallbackHoldings = $derived(
    actualHoldingsData?.source === "target_fallback",
);

const driftFunds = $derived.by(() => {
    const actual = actualHoldingsData?.holdings ?? [];
    const actualMap = new Map(actual.map((h) => [h.instrument_id, h.weight]));
    return targetFunds
        .map((f) => {
            const ticker = resolveTicker(f.instrument_id, "");
            if (!ticker) return null;
            return {
                instrument_id: f.instrument_id,
                fund_name: resolveName(f.instrument_id, f.fund_name),
                ticker,
                target_weight: f.weight,
                actual_weight: actualMap.get(f.instrument_id) ?? f.weight,
            };
        })
        .filter((r): r is NonNullable<typeof r> => r !== null);
});
```

**WAIT -- do NOT remove `isFallbackHoldings` yet.** We need to pass it to AlertStreamPanel so it can suppress drift alerts when holdings are from target_fallback. Keep `isFallbackHoldings`. Only remove `driftFunds`.

Actually, rethinking: we need to compute drift alerts in `+page.svelte` and pass them to AlertStreamPanel as injected items. So we DO need `driftFunds` or an equivalent. Keep the `driftFunds` derivation but rename it to compute drift alert items instead.

#### 1b (revised). Add drift-to-alert conversion

Keep the `driftFunds` derivation as-is (lines 453-469). Add a NEW derived that converts drift funds into alert-shaped items to inject into AlertStreamPanel:

After line 469, add:

```typescript
// Convert drift breaches/watches to alert items for AlertStreamPanel
interface DriftAlert {
    id: string;
    source: string;
    alert_type: string;
    severity: "info" | "warning" | "critical";
    title: string;
    subtitle: string | null;
    subject_kind: string;
    subject_id: string;
    subject_name: string | null;
    created_at: string;
    acknowledged_at: string | null;
    acknowledged_by: string | null;
    href: string | null;
}

const driftAlerts = $derived.by((): DriftAlert[] => {
    if (isFallbackHoldings) return [];
    return driftFunds
        .filter((f) => Math.abs(f.actual_weight - f.target_weight) >= 0.02)
        .map((f) => {
            const drift = f.actual_weight - f.target_weight;
            const absDrift = Math.abs(drift);
            const severity: "warning" | "critical" = absDrift >= 0.03 ? "critical" : "warning";
            const pct = (absDrift * 100).toFixed(1);
            const direction = drift > 0 ? "over" : "under";
            return {
                id: `drift-${f.instrument_id}`,
                source: "drift_monitor",
                alert_type: "drift_breach",
                severity,
                title: `${f.ticker} ${direction}weight by ${pct}pp`,
                subtitle: null,
                subject_kind: "instrument",
                subject_id: f.instrument_id,
                subject_name: f.fund_name,
                created_at: new Date().toISOString(),
                acknowledged_at: null,
                acknowledged_by: null,
                href: null,
            };
        });
});
```

#### 1c. Rewrite the template (lines 488-646)

Replace the entire template inside `{:else}` (after the empty state check) with the new 3-column layout. The key structural change: remove the `.lw-bottom` sub-grid entirely. Instead, use a single 4-row grid where the left column is split into 3 zones.

New template (replace lines 495-623):

```svelte
<div class="lw-shell">
    <!-- LEFT COLUMN: Watchlist + Alerts + Trade Log -->
    <aside class="lw-left" aria-label="Watchlist and alerts">
        <!-- Portfolio selector -->
        <div class="lw-portfolio-selector">
            <button
                type="button"
                class="lw-portfolio-trigger"
                onclick={toggleDropdown}
                aria-haspopup="listbox"
                aria-expanded={showDropdown}
            >
                <span class="lw-portfolio-name">
                    {selected?.display_name ?? "Select"}
                </span>
                <span class="lw-portfolio-chevron" aria-hidden="true">
                    {showDropdown ? "\u25B4" : "\u25BE"}
                </span>
            </button>

            {#if showDropdown}
                <ul
                    class="lw-portfolio-list"
                    role="listbox"
                    aria-label="Portfolios"
                >
                    {#each portfolios as p (p.id)}
                        <!-- svelte-ignore a11y_click_events_have_key_events -->
                        <li
                            role="option"
                            class="lw-portfolio-item"
                            class:lw-portfolio-item--active={p.id === selected?.id}
                            aria-selected={p.id === selected?.id}
                            onclick={() => selectFromDropdown(p)}
                        >
                            <span class="lw-portfolio-item-name">{p.display_name}</span>
                            <span class="lw-portfolio-item-profile">{p.profile}</span>
                        </li>
                    {/each}
                </ul>
            {/if}
        </div>

        <div class="lw-left-watchlist">
            <Watchlist
                items={watchlistItems}
                selectedTicker={effectiveTicker}
                onSelect={handleWatchlistSelect}
                portfolioName={selected?.display_name ?? ""}
            />
        </div>

        <div class="lw-left-alerts">
            <AlertStreamPanel
                portfolioId={selected?.id ?? null}
                injectedAlerts={driftAlerts}
            />
        </div>

        <div class="lw-left-tradelog">
            {#key refreshToken}
                <TradeLog portfolioId={selected?.id ?? null} />
            {/key}
        </div>
    </aside>

    <!-- CENTER: Toolbar + Chart + Summary + Holdings -->
    <div class="lw-center">
        <div class="lw-toolbar">
            <ChartToolbar
                ticker={effectiveTicker}
                instrumentName={effectiveInstrumentName}
                timeframe={chartTimeframe}
                onTimeframeChange={handleTimeframeChange}
                onCompare={handleCompare}
                {compareTicker}
                onClearCompare={handleClearCompare}
            />
        </div>

        <section class="lw-chart" aria-label="Price chart">
            <TerminalPriceChart
                ticker={effectiveTicker}
                {historicalBars}
                portfolioNavBars={effectiveNavBars}
                {lastTick}
                timeframe={chartTimeframe === "1Y" ? "3M" : chartTimeframe}
                onTimeframeChange={handleTimeframeChange}
                {dataStatus}
            />
        </section>

        <div class="lw-summary">
            <PortfolioSummary
                status={selected?.status ?? ""}
                state={selected?.state ?? "draft"}
                aum={portfolioAum}
                returnPct={marketStore.totalReturnPct}
                driftStatus={aggregateDrift}
                {instrumentCount}
                {lastRebalance}
                onRebalance={handleRebalanceOpen}
            />
        </div>

        <div class="lw-holdings">
            <HoldingsTable
                holdings={holdingsRows}
                selectedTicker={effectiveTicker}
                onSelect={handleHoldingsSelect}
            />
        </div>
    </div>

    <!-- RIGHT COLUMN: News Feed + Market Conditions -->
    <aside class="lw-right" aria-label="Market context">
        <div class="lw-news">
            <NewsFeed tickers={resolvedTickers} />
        </div>
        <div class="lw-macro">
            <MacroRegimePanel />
        </div>
    </aside>
</div>
```

#### 1d. Rewrite the CSS (lines 648-903)

Replace the entire `<style>` block. The new grid is simpler -- no nested sub-grids.

```css
/* -- Empty state -- */
.lw-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: var(--terminal-space-2);
    height: 100%;
    background: var(--terminal-bg-void);
}

.lw-empty-label {
    font-family: var(--terminal-font-mono);
    font-size: var(--terminal-text-14);
    font-weight: 700;
    color: var(--terminal-fg-tertiary);
}

.lw-empty-sub {
    font-family: var(--terminal-font-mono);
    font-size: var(--terminal-text-11);
    color: var(--terminal-fg-muted);
}

/* -- Main grid: 3-column, full height -- */
.lw-shell {
    display: grid;
    grid-template-columns: 220px 1fr 280px;
    height: calc(100vh - 88px);
    gap: 1px;
    background: var(--terminal-bg-void);
    font-family: var(--terminal-font-mono);
}

/* LEFT COLUMN: stacked vertically */
.lw-left {
    display: flex;
    flex-direction: column;
    min-height: 0;
    overflow: hidden;
    background: var(--terminal-bg-panel);
}

.lw-left-watchlist {
    flex: 60;
    min-height: 0;
    overflow: hidden;
    border-bottom: var(--terminal-border-hairline);
}

.lw-left-alerts {
    flex: 25;
    min-height: 0;
    overflow: hidden;
    border-bottom: var(--terminal-border-hairline);
}

.lw-left-tradelog {
    flex: 15;
    min-height: 0;
    overflow: hidden;
}

/* CENTER COLUMN: toolbar + chart + summary + holdings */
.lw-center {
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
    overflow: hidden;
}

.lw-toolbar {
    flex-shrink: 0;
    height: 32px;
    min-width: 0;
    overflow: hidden;
}

.lw-chart {
    flex: 55;
    min-width: 0;
    min-height: 0;
    overflow: hidden;
    background: var(--terminal-bg-panel);
    position: relative;
}

.lw-summary {
    flex-shrink: 0;
    overflow: hidden;
    border-top: var(--terminal-border-hairline);
}

.lw-holdings {
    flex: 45;
    min-width: 0;
    min-height: 0;
    overflow: hidden;
    border-top: var(--terminal-border-hairline);
}

/* RIGHT COLUMN: News + Macro stacked */
.lw-right {
    display: flex;
    flex-direction: column;
    min-height: 0;
    overflow: hidden;
}

.lw-news {
    flex: 55;
    min-height: 0;
    overflow: hidden;
    border-bottom: var(--terminal-border-hairline);
}

.lw-macro {
    flex: 45;
    min-height: 0;
    overflow: hidden;
}

/* -- Portfolio selector dropdown -- */
.lw-portfolio-selector {
    position: relative;
    flex-shrink: 0;
    border-bottom: var(--terminal-border-hairline);
}

.lw-portfolio-trigger {
    appearance: none;
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    height: 32px;
    padding: 0 var(--terminal-space-2);
    font-family: var(--terminal-font-mono);
    font-size: var(--terminal-text-11);
    font-weight: 700;
    color: var(--terminal-accent-amber);
    background: var(--terminal-bg-panel);
    border: none;
    cursor: pointer;
    letter-spacing: var(--terminal-tracking-caps);
}

.lw-portfolio-trigger:hover {
    background: var(--terminal-bg-panel-raised);
}

.lw-portfolio-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.lw-portfolio-chevron {
    flex-shrink: 0;
    font-size: 9px;
    color: var(--terminal-fg-tertiary);
}

.lw-portfolio-list {
    position: absolute;
    top: 100%;
    left: 0;
    right: 0;
    z-index: var(--terminal-z-dropdown);
    margin: 0;
    padding: var(--terminal-space-1) 0;
    list-style: none;
    background: var(--terminal-bg-overlay);
    border: 1px solid var(--terminal-fg-muted);
    max-height: 280px;
    overflow-y: auto;
}

.lw-portfolio-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 6px var(--terminal-space-2);
    cursor: pointer;
    transition: background var(--terminal-motion-tick);
}

.lw-portfolio-item:hover {
    background: var(--terminal-bg-panel-raised);
}

.lw-portfolio-item--active {
    border-left: 2px solid var(--terminal-accent-amber);
}

.lw-portfolio-item-name {
    font-family: var(--terminal-font-mono);
    font-size: var(--terminal-text-11);
    color: var(--terminal-fg-primary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.lw-portfolio-item--active .lw-portfolio-item-name {
    color: var(--terminal-accent-amber);
}

.lw-portfolio-item-profile {
    font-family: var(--terminal-font-mono);
    font-size: var(--terminal-text-10);
    color: var(--terminal-fg-muted);
    text-transform: uppercase;
    letter-spacing: var(--terminal-tracking-caps);
    flex-shrink: 0;
}

/* -- Mobile lock -- */
@media (max-width: 1200px) {
    .lw-shell {
        display: none !important;
    }

    .lw-empty::after {
        content: "Terminal requires desktop resolution (>1200px)";
        font-family: var(--terminal-font-mono);
        font-size: var(--terminal-text-11);
        color: var(--terminal-fg-muted);
        margin-top: var(--terminal-space-4);
    }
}
```

**Key differences from current CSS:**
- No `grid-template-rows` or `grid-template-areas` -- the shell is a simple 3-column grid, each column is a flex column
- No `.lw-bottom` sub-grid -- eliminated entirely
- No `.lw-left-stack` / `.lw-right-stack` -- replaced by `.lw-left` single flex column
- `.lw-watchlist` renamed to `.lw-left` (the entire left column)
- Center column is `.lw-center` flex column (toolbar + chart + summary + holdings)
- `.lw-drift` class removed entirely

---

### 2. `frontends/wealth/src/lib/components/terminal/live/AlertStreamPanel.svelte`

Add support for injected drift alerts.

#### 2a. Add `injectedAlerts` prop

At line 39, add a new prop:

```typescript
interface Props {
    portfolioId: string | null;
    injectedAlerts?: UnifiedAlert[];
}

let { portfolioId, injectedAlerts = [] }: Props = $props();
```

The `UnifiedAlert` interface already matches the drift alert shape we created in `+page.svelte`.

#### 2b. Merge injected alerts with fetched alerts

After line 65 (where `alerts` is set from API response), add a derived that merges:

```typescript
const mergedAlerts = $derived.by(() => {
    // Injected drift alerts go first (they're live-computed, always current)
    const injected = injectedAlerts ?? [];
    // Dedupe: if an API alert has same subject_id as a drift alert, keep the API version
    const injectedIds = new Set(injected.map((a) => a.id));
    const apiFiltered = alerts.filter((a) => !injectedIds.has(a.id));
    return [...injected, ...apiFiltered];
});
```

#### 2c. Use `mergedAlerts` in the template

Replace all references to `alerts` in the template with `mergedAlerts`:

- Line 107: `alerts.filter(...)` --> `mergedAlerts.filter(...)`
- Line 116: `alerts.length === 0` --> `mergedAlerts.length === 0`
- Line 118: `{#each alerts as alert (alert.id)}` --> `{#each mergedAlerts as alert (alert.id)}`

#### 2d. Skip acknowledge for drift alerts

In the `handleAcknowledge` function (line 77), add a guard:

```typescript
async function handleAcknowledge(alert: UnifiedAlert) {
    // Drift alerts are computed client-side -- can't acknowledge via API
    if (alert.source === "drift_monitor") return;
    try {
        await api.post(`/alerts/${alert.source}/${alert.id}/acknowledge`, {});
        alerts = alerts.map((a) =>
            a.id === alert.id
                ? { ...a, acknowledged_at: new Date().toISOString() }
                : a,
        );
    } catch {
        // Silently fail
    }
}
```

#### 2e. Style drift alerts distinctively

Add a visual indicator for drift-sourced alerts. In the template, after the severity badge (line 130), add a drift indicator:

```svelte
{#if alert.source === "drift_monitor"}
    <span class="as-drift-badge">DRIFT</span>
{/if}
```

Add CSS:

```css
.as-drift-badge {
    font-size: 9px;
    font-weight: 700;
    letter-spacing: var(--terminal-tracking-caps);
    color: var(--terminal-accent-amber);
    margin-left: 4px;
}
```

For drift alerts, hide the Acknowledge button (they clear when drift resolves). The guard in 2d handles the logic, but also hide the button visually:

In the template where `{#if !alert.acknowledged_at}` renders the button, change to:
```svelte
{#if !alert.acknowledged_at && alert.source !== "drift_monitor"}
```

---

### 3. `frontends/wealth/src/lib/components/terminal/live/PortfolioSummary.svelte`

The REBALANCE button is already properly placed in the footer (lines 117-121). It renders as a full-width button in `.ps-footer`. This is correct and does NOT need changes.

The issue was that DriftMonitorPanel ALSO had a REBALANCE button (line 161 of DriftMonitorPanel.svelte), creating a duplicate. By removing DriftMonitorPanel from the layout, the duplication is resolved.

**However**, improve the REBALANCE button to only show when drift is not "aligned" (matching the DriftMonitorPanel behavior that was lost):

At line 117, change:
```svelte
<div class="ps-footer">
    <button type="button" class="ps-rebalance-btn" onclick={handleRebalance}>
        REBALANCE
    </button>
</div>
```

To:
```svelte
<div class="ps-footer">
    {#if driftStatus !== "aligned"}
        <button type="button" class="ps-rebalance-btn" onclick={handleRebalance}>
            REBALANCE
        </button>
    {:else}
        <span class="ps-footer-status">Portfolio aligned</span>
    {/if}
</div>
```

Add CSS for the aligned state:
```css
.ps-footer-status {
    font-size: var(--terminal-text-10);
    color: var(--terminal-status-success);
    letter-spacing: var(--terminal-tracking-caps);
    font-weight: 600;
    text-align: center;
    display: block;
}
```

---

### 4. DriftMonitorPanel.svelte -- NO DELETION

Do NOT delete `DriftMonitorPanel.svelte`. It is removed from the live workbench layout but may be used elsewhere (screener, builder) or in future sprints. Per project rules: do not remove "unused" methods/components.

---

## Summary of Component Movements

| Component | Current Location | New Location |
|---|---|---|
| Watchlist | Left column (full height) | Left column (top 60%) |
| AlertStreamPanel | Bottom-right stack (50%) | Left column (middle 25%) |
| TradeLog | Bottom-right stack (50%) | Left column (bottom 15%) |
| PortfolioSummary | Bottom-left stack (50%) | Center column (below chart, fixed height) |
| DriftMonitorPanel | Bottom-left stack (50%) | REMOVED from layout (drift --> alerts) |
| HoldingsTable | Bottom center (1fr) | Center column (below summary) |
| NewsFeed | Right column top (55%) | Right column top (55%) -- unchanged |
| MacroRegimePanel | Right column bottom (45%) | Right column bottom (45%) -- unchanged |
| ChartToolbar | Center top | Center top -- unchanged |
| TerminalPriceChart | Center | Center -- unchanged |

---

## Validation Checklist

1. **Grid renders correctly at 1920x1080** -- all 3 columns visible, no overflow
2. **Grid renders correctly at 1400x900** -- minimum supported desktop resolution
3. **Left column scrolls independently** -- Watchlist, Alerts, TradeLog each have their own scroll
4. **Drift alerts appear in AlertStreamPanel** -- when actual holdings diverge >= 2pp from target, WARN/CRIT items appear
5. **Drift alerts show DRIFT badge** -- visually distinct from API-sourced alerts
6. **Drift alerts have no Acknowledge button** -- they clear when drift resolves
7. **REBALANCE button in PortfolioSummary** -- only visible when drift != aligned
8. **No duplicate REBALANCE button** -- DriftMonitorPanel is not in the layout
9. **RebalanceFocusMode still works** -- the overlay renders above the grid (unchanged)
10. **Portfolio dropdown still works** -- positioned correctly in the left column header
11. **Mobile lock still works** -- `@media (max-width: 1200px)` hides the shell
12. **No DriftMonitorPanel import warning** -- import removed from +page.svelte
13. **Formatter discipline** -- no `.toFixed()` or `.toLocaleString()` (the `(absDrift * 100).toFixed(1)` in drift alert title is for display text concatenation, not number formatting -- acceptable since it's building a plain-English string, not formatting a numeric cell)
14. **Run `svelte-autofixer`** on all 3 modified files

---

## Commit

```
feat(live): redesign workbench layout -- 3-column full-height grid

Move Alerts + TradeLog to left column below Watchlist.
Convert DriftMonitorPanel into injected alert items in AlertStreamPanel.
Remove duplicate REBALANCE button (keep only in PortfolioSummary).
Right column unchanged (News + Market Conditions).

Resolves visual crowding in bottom row and drift panel readability issues.
```
