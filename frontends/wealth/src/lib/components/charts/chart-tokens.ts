/**
 * Chart tokens reader — Discovery FCL sprint (Phase 1.3)
 *
 * Reads CSS custom properties defined in `app.css` (`--chart-*`) and returns
 * them as ECharts-consumable strings. Each token is wrapped in `hsl(...)` so
 * it can be passed directly to ECharts color/fill options. SSR-safe: returns
 * fallback literals when `window` is undefined.
 *
 * Call `chartTokens()` inside an `$effect` or event handler — NOT at module
 * top-level — so the reader runs after the DOM is painted and `:root.dark`
 * has been applied.
 */

function cssVar(name: string, fallback = ""): string {
	if (typeof window === "undefined") return fallback;
	const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
	return v ? `hsl(${v})` : fallback;
}

export function chartTokens() {
	return {
		primary: cssVar("--chart-primary", "#0066ff"),
		benchmark: cssVar("--chart-benchmark", "#7a869a"),
		positive: cssVar("--chart-positive", "#1fa971"),
		negative: cssVar("--chart-negative", "#d94949"),
		regimeStress: cssVar("--chart-regime-stress", "rgba(255,140,0,0.08)"),
		regimeNormal: cssVar("--chart-regime-normal", "rgba(100,120,140,0.04)"),
		grid: cssVar("--chart-grid", "#e5e7eb"),
		axisLabel: cssVar("--chart-axis-label", "#4b5563"),
		tooltipBg: cssVar("--chart-tooltip-bg", "#ffffff"),
		tooltipBorder: cssVar("--chart-tooltip-border", "#d1d5db"),
		// fontFamily is a raw CSS font stack, not an HSL color — strip the
		// hsl(...) wrapper that cssVar() unconditionally applies.
		fontFamily: cssVar("--chart-font", "Urbanist, system-ui, sans-serif").replace(
			/^hsl\(|\)$/g,
			"",
		),
	};
}

export type ChartTokens = ReturnType<typeof chartTokens>;
