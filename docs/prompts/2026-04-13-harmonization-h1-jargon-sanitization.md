# Harmonization H1 -- Quant Jargon Sanitization (22 leaks across 16 files)

**Date:** 2026-04-13
**Branch:** `feat/harmonization-h1-jargon` (off `main`)
**Scope:** Frontend only -- pure string/text replacements, zero logic changes, zero backend changes
**Risk:** LOW -- text-only edits, no schema/route/logic changes
**Priority:** HIGH -- quant jargon in user-facing strings violates institutional presentation standards

---

## Problem Statement

22 quant jargon leaks exist across 16 frontend files in `frontends/wealth/src/`. Terms like "CVaR", "CLARABEL", "GARCH", "Ledoit-Wolf", "Black-Litterman", and "Heuristic Recovery" are exposed in user-visible labels, tooltips, aria-labels, and placeholder text. These are implementation details that institutional PMs should never see. The target vocabulary is already established in `$lib/i18n/quant-labels.ts` and `$lib/types/taa.ts` -- this session aligns all remaining surfaces.

---

## Constraints

1. **Zero logic changes.** Every edit is a string literal replacement or a small label-dictionary addition. No control flow, no data flow, no imports (except one new map in AdvisorTab).
2. **Comments are OK.** The exit-criteria grep excludes comments (`//`, `<!--`, `/*`). Internal code comments that reference CVaR/GARCH for developer context may remain.
3. **Do not touch `quant-labels.ts` or `taa.ts`.** Those are already correct and are the authoritative label source.
4. **Do not touch backend files.** This is frontend-only.
5. **Preserve existing HTML entities** (e.g., `&rarr;`) and Unicode characters (e.g., `\u2026`, subscript digits).

---

## Replacements -- Terminal Components (7 leaks)

### File 1: `frontends/wealth/src/lib/components/terminal/builder/RiskTab.svelte`

**Leak 1 (line 68):** Chart y-axis category label exposes "CVaR".

```
old_string: data: ["CVaR"]
new_string: data: ["Tail Loss"]
```

**Leak 2 (line 183):** Aria label on the stacked bar chart exposes "CVaR".

```
old_string: ariaLabel="CVaR contribution stacked bar"
new_string: ariaLabel="Tail loss contribution stacked bar"
```

---

### File 2: `frontends/wealth/src/lib/components/terminal/builder/AdvisorTab.svelte`

**Leak 3 (line 146):** The advisor notes section renders raw backend API keys via `.replace(/_/g, " ")`. Backend keys include `current_cvar_95`, `cvar_limit`, `cvar_gap` which render as "current cvar 95", "cvar limit", "cvar gap". Fix: add a label dictionary and use it with fallback to the replace pattern.

This requires TWO edits in the same file:

**Edit A -- Add the label dictionary after the `formatAdvisorValue` function (after line 53, before `</script>`):**

```
old_string: 	return String(value);
	}
</script>

new_string: 	return String(value);
	}

	/** Map raw backend keys to institutional display labels. */
	const ADVISOR_KEY_LABELS: Record<string, string> = {
		portfolio_id: "Portfolio",
		profile: "Profile",
		current_cvar_95: "Current Tail Loss (95%)",
		cvar_limit: "Tail Loss Limit",
		cvar_gap: "Risk Budget Gap",
		detail_endpoint: "Detail Endpoint",
		note: "Note",
	};

	function advisorKeyLabel(key: string): string {
		return ADVISOR_KEY_LABELS[key] ?? key.replace(/_/g, " ");
	}
</script>
```

**Edit B -- Replace the raw `.replace()` call in the template (line 146):**

```
old_string: <dt class="at-advisor-key">{key.replace(/_/g, " ")}</dt>
new_string: <dt class="at-advisor-key">{advisorKeyLabel(key)}</dt>
```

---

### File 3: `frontends/wealth/src/lib/state/portfolio-workspace.svelte.ts`

**Leak 4 (line 204):** Cascade phase label "Heuristic Recovery" exposes optimizer internals.

```
old_string: { key: "heuristic", label: "Heuristic Recovery", status: "pending" },
new_string: { key: "heuristic", label: "Recovery", status: "pending" },
```

---

### File 4: `frontends/wealth/src/lib/components/terminal/builder/CascadeTimeline.svelte`

**Leak 5 (line 38):** Aria label exposes "Optimizer cascade".

```
old_string: aria-label="Optimizer cascade timeline"
new_string: aria-label="Construction phase timeline"
```

---

### File 5: `frontends/wealth/src/lib/components/terminal/shell/TerminalTopNav.svelte`

**Leak 6 (line 238):** Top nav regime label displays raw "REGIME".

```
old_string: <span class="tn-regime-label">REGIME</span>
new_string: <span class="tn-regime-label">MARKET</span>
```

---

### File 6: `frontends/wealth/src/lib/components/terminal/live/MacroRegimePanel.svelte`

**Leak 7 (line 111):** Panel header displays "MACRO REGIME".

```
old_string: <span class="mr-label">MACRO REGIME</span>
new_string: <span class="mr-label">MARKET CONDITIONS</span>
```

---

## Replacements -- Display Mappings (3 leaks)

### File 7: `frontends/wealth/src/lib/components/terminal/shell/TerminalContextRail.svelte`

**Leak 8 (line 74-75):** Switch case returns raw "REGIME".

```
old_string: 		case "regime":
				return "REGIME";
new_string: 		case "regime":
				return "ENVIRONMENT";
```

---

### File 8: `frontends/wealth/src/lib/components/terminal/focus-mode/FocusMode.svelte`

**Leak 9 (line 81-82):** Same switch case pattern.

```
old_string: 		case "regime":
				return "REGIME";
new_string: 		case "regime":
				return "ENVIRONMENT";
```

---

### File 9: `frontends/wealth/src/lib/constants/regime.ts`

**Leak 10 (lines 3-8):** Regime labels use "Risk On" / "Risk Off" / "Crisis" instead of institutional vocabulary established in `taa.ts` (Expansion / Defensive / Stress / Inflation).

```
old_string: export const regimeLabels: Record<string, string> = {
	RISK_ON: "Risk On",
	RISK_OFF: "Risk Off",
	INFLATION: "Inflation",
	CRISIS: "Crisis",
};
new_string: export const regimeLabels: Record<string, string> = {
	RISK_ON: "Expansion",
	RISK_OFF: "Defensive",
	INFLATION: "Inflation",
	CRISIS: "Stress",
};
```

**Leak 11 (line 28):** `regimeMultiplierLabel` returns "CVaR tightened by X%".

```
old_string: return `CVaR tightened by ${pct}%`;
new_string: return `Risk budget tightened by ${pct}%`;
```

---

## Replacements -- Legacy Portfolio Components (12 leaks)

### File 10: `frontends/wealth/src/lib/components/portfolio/CalibrationPanel.svelte`

**Leak 12 (line 334):** Mandate description exposes "CVaR".

```
old_string: description="Risk profile archetype — drives downstream defaults for CVaR, diversification, and turnover."
new_string: description="Risk profile archetype — drives downstream defaults for tail loss budget, diversification, and turnover."
```

**Leak 13 (line 343):** CVaR limit description.

```
old_string: description="Maximum CVaR the optimizer may allow at the 95% level."
new_string: description="Maximum tail loss (95% confidence) the portfolio may carry."
```

**Leak 14 (line 410):** Toggle label exposes "Black-Litterman".

```
old_string: label="Black-Litterman blending"
new_string: label="Expected return blending"
```

**Leak 15 (lines 432-433):** Toggle label and description expose "GARCH(1,1)".

```
old_string: 					label="GARCH forward volatility"
						description="Use GARCH(1,1) conditional volatility instead of realized vol."
new_string: 					label="Forward-looking volatility"
						description="Use forward-looking conditional volatility instead of realized vol."
```

**Leak 16 (line 467):** Advisor description exposes "CVaR".

```
old_string: description="Enable the credit-side advisor that recommends fund additions to close CVaR gaps."
new_string: description="Enable the credit-side advisor that recommends fund additions to close risk budget gaps."
```

**Leak 17 (line 474):** CVaR confidence level label.

```
old_string: label="CVaR confidence level"
new_string: label="Tail loss confidence level"
```

**Leak 18 (line 483):** Risk aversion label exposes Greek letter notation.

```
old_string: label="Risk aversion (λ)"
new_string: label="Risk aversion"
```

**Leak 19 (line 497):** Shrinkage description exposes "Ledoit-Wolf".

```
old_string: description="Manual Ledoit-Wolf shrinkage (0..1). Leave at default for auto-selection."
new_string: description="Covariance shrinkage override (0..1). Leave at default for auto-selection."
```

---

### File 11: `frontends/wealth/src/lib/components/portfolio/ConstructionNarrative.svelte`

**Leak 20 (line 52):** Phase label exposes "CLARABEL optimizer cascade".

```
old_string: return "Running CLARABEL optimizer cascade…";
new_string: return "Optimizing portfolio allocation…";
```

NOTE: The `…` is the Unicode ellipsis character (U+2026). Match it exactly -- do NOT use `...` (three dots).

---

### File 12: `frontends/wealth/src/lib/components/model-portfolio/ConstructionAdvisor.svelte`

**Leak 21a (line 266):** Subtitle exposes "CVaR".

```
old_string: {advice.profile} — CVaR {formatPercent(advice.current_cvar_95)} (limit {formatPercent(advice.cvar_limit)})
new_string: {advice.profile} — Tail Loss {formatPercent(advice.current_cvar_95)} (limit {formatPercent(advice.cvar_limit)})
```

**Leak 21b (line 318):** Table header "Proj CVaR".

```
old_string: <th class="ca-th-num">Proj CVaR</th>
new_string: <th class="ca-th-num">Proj Risk</th>
```

**Leak 21c (line 387):** Alternative profile text exposes "CVaR limit".

```
old_string: (CVaR limit {formatPercent(alt.cvar_limit)}) — current portfolio would pass.
new_string: (risk limit {formatPercent(alt.cvar_limit)}) — current portfolio would pass.
```

**Leak 21d (line 399):** Minimum viable set text exposes "CVaR".

```
old_string: Add {mvsNames.join(" + ")} → projected CVaR: {formatPercent(advice.minimum_viable_set.projected_cvar_95)}
new_string: Add {mvsNames.join(" + ")} → projected tail loss: {formatPercent(advice.minimum_viable_set.projected_cvar_95)}
```

**Leak 21e (line 434):** Batch dialog metadata exposes "Projected CVaR".

```
old_string: { label: "Projected CVaR", value: advice?.minimum_viable_set ? formatPercent(advice.minimum_viable_set.projected_cvar_95) : "—" },
new_string: { label: "Projected Tail Loss", value: advice?.minimum_viable_set ? formatPercent(advice.minimum_viable_set.projected_cvar_95) : "—" },
```

---

### File 13: `frontends/wealth/src/lib/components/model-portfolio/FundSelectionEditor.svelte`

**Leak 22a (line 329):** ConsequenceDialog exposes "4-phase CLARABEL cascade optimizer".

```
old_string: impactSummary="Fund selection will be updated and the 4-phase CLARABEL cascade optimizer will re-run. This may take 5-10 seconds."
new_string: impactSummary="Fund selection will be updated and the portfolio will be re-optimized. This may take 5-10 seconds."
```

---

### File 14: `frontends/wealth/src/lib/components/portfolio/live/TerminalAllocator.svelte`

**Leak 22b (line 106):** Button label exposes "CLARABEL OPTIMIZER".

```
old_string: USE CLARABEL OPTIMIZER &rarr;
new_string: OPTIMIZE ALLOCATION &rarr;
```

---

### File 15: `frontends/wealth/src/lib/components/model-portfolio/RebalancePreview.svelte`

**Leak 22c (line 83):** Warning banner title exposes "CVaR".

```
old_string: <span class="text-[13px] font-semibold text-[#f59e0b] block">CVaR Limit Warning</span>
new_string: <span class="text-[13px] font-semibold text-[#f59e0b] block">Risk Limit Warning</span>
```

**Leak 22d (line 85):** Warning body exposes "CVaR" with Unicode subscript.

```
old_string: Projected CVaR₉₅ ({formatPercent((preview.cvar_95_projected ?? 0) * 100)}) is approaching
new_string: Projected tail loss ({formatPercent((preview.cvar_95_projected ?? 0) * 100)}) is approaching
```

---

### File 16: `frontends/wealth/src/lib/components/portfolio/StressTestPanel.svelte`

**Leak 22e (line 205):** KPI label exposes "CVaR Stressed".

```
old_string: <span class="stress-kpi-label">CVaR Stressed</span>
new_string: <span class="stress-kpi-label">Stressed Tail Loss</span>
```

---

### File 17: `frontends/wealth/src/lib/components/portfolio/StressCustomShockTab.svelte`

**Leak 22f (line 79):** Result label exposes "Stressed CVaR".

```
old_string: <span class="scs-label">Stressed CVaR</span>
new_string: <span class="scs-label">Stressed Tail Loss</span>
```

---

### File 18: `frontends/wealth/src/lib/components/research/terminal/TerminalResearchChart.svelte`

**Leak 22g (line 271):** Summary header exposes "GARCH VOL".

```
old_string: GARCH VOL
new_string: FORWARD VOL
```

**Leak 22h (line 287):** Placeholder description exposes "GARCH volatility".

```
old_string: drawdown, GARCH volatility and macro regime overlays.
new_string: drawdown, conditional volatility and regime overlays.
```

**Leak 22i (line 301):** Pane label exposes "GARCH VOLATILITY".

```
old_string: <div class="rc-pane-label">GARCH VOLATILITY</div>
new_string: <div class="rc-pane-label">CONDITIONAL VOLATILITY</div>
```

---

## Execution Order

Execute all edits in file order (1 through 18). For files with multiple edits, process them from BOTTOM to TOP within the file to avoid line number drift. The AdvisorTab edits MUST go Edit A first (adds the function), then Edit B (uses it).

---

## Verification

After all edits, run:

```bash
# 1. Jargon grep -- must return ZERO hits (comments excluded)
cd frontends/wealth
grep -ri "cvar\|clarabel\|garch\b\|ledoit\|black.litterman" src/ \
  --include="*.svelte" --include="*.ts" | grep -v "//\|<!--\|/\*\|cvar_\|\.cvar\|cvarStressed\|cvar_95\|cvar_limit\|cvar_gap\|cvar_warning\|cvar_level"

# 2. The STRICT grep: only human-readable label strings (not JS property access)
grep -rn '"[^"]*CVaR[^"]*"\|>[^<]*CVaR\|>[^<]*CLARABEL\|>[^<]*GARCH\|>[^<]*Ledoit\|>[^<]*Black-Litterman' src/ \
  --include="*.svelte" --include="*.ts"

# 3. Svelte check
pnpm check

# 4. Full backend gate (nothing should break)
cd ../..
make check
```

The STRICT grep (#2) is the authoritative gate. It matches quoted strings containing banned terms and HTML text content containing them. This catches labels, descriptions, and aria-labels while ignoring JS property names like `cvar_95_projected` or `cvarStressed` which are data keys, not user-visible text.

---

## Commit

```
fix(wealth-frontend): sanitize 22 quant jargon leaks across 16 files

Replace user-visible instances of CVaR, CLARABEL, GARCH, Ledoit-Wolf,
Black-Litterman, and Heuristic Recovery with institutional vocabulary:
Tail Loss, Forward Volatility, Covariance Shrinkage, Expected Return
Blending, Risk Budget, Expansion/Defensive/Stress regime labels.

Zero logic changes -- pure string replacements and one label dictionary
addition in AdvisorTab for backend API key humanization.

Session H1 of the Terminal Harmonization Plan.
```
