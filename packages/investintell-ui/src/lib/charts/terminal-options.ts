/**
 * Netz Wealth OS — createTerminalChartOptions()
 * =============================================
 *
 * Source of truth: docs/plans/2026-04-11-terminal-unification-master-plan.md §1.2
 *
 * SINGLE factory that owns the brutalist aesthetic for every
 * chart inside `(terminal)/`. Callers supply only `series` /
 * `dataset` / `markArea` — never grid, axis, tooltip, legend,
 * font, palette, animation. Those live here.
 *
 * Contract:
 *   - Reads CSS custom properties from `tokens/terminal.css` at
 *     runtime. SSR-safe (returns documented defaults when
 *     `document` is undefined).
 *   - ZERO hex literals (only documented SSR fallbacks that must
 *     match the token source of truth).
 *   - Forces grid + dotted split lines, square tooltips (zero
 *     radius, hairline border), monospace typography.
 *   - Consumes `choreo` for staggered animation delays.
 *   - Exposes `terminalPalette` so wrappers can color series
 *     deterministically by slot.
 */

import type { EChartsOption } from "echarts";
import {
	choreo,
	terminalDuration,
	terminalEasing,
	prefersReducedMotion,
	type ChoreoSlot,
} from "./choreo.js";

/**
 * Eight-slot ordinal palette. Fixed length — the rest of the
 * factory (and every pattern wrapper) assumes exactly 8 entries.
 */
export type TerminalDatavizPalette = readonly [
	string,
	string,
	string,
	string,
	string,
	string,
	string,
	string,
];

/**
 * Tokens read from `tokens/terminal.css` at runtime. Every value
 * returned here maps 1:1 to a `--terminal-*` custom property; the
 * hex fallbacks are documented mirrors of the token file and
 * exist only so server-rendered ECharts markup does not explode.
 */
export interface TerminalChartTokens {
	bgVoid: string;
	bgPanel: string;
	bgPanelRaised: string;
	fgPrimary: string;
	fgSecondary: string;
	fgTertiary: string;
	fgMuted: string;
	accentAmber: string;
	accentCyan: string;
	accentViolet: string;
	statusSuccess: string;
	statusWarn: string;
	statusError: string;
	dataviz: TerminalDatavizPalette;
	fontMono: string;
	text10: number;
	text11: number;
	text12: number;
	text14: number;
}

const DEFAULT_DATAVIZ: TerminalDatavizPalette = [
	"#ffb020",
	"#00e5ff",
	"#a080ff",
	"#3ed67b",
	"#ff7a4a",
	"#f0f0e6",
	"#6b8cff",
	"#b8b8b0",
] as const;

/** SSR-safe default mirror of `tokens/terminal.css`. */
const DEFAULT_TOKENS: TerminalChartTokens = {
	bgVoid: "#000000",
	bgPanel: "#050505",
	bgPanelRaised: "#0a0a0a",
	fgPrimary: "#f5f5f0",
	fgSecondary: "#b8b8b0",
	fgTertiary: "#6b6b63",
	fgMuted: "#3d3d38",
	accentAmber: "#ffb020",
	accentCyan: "#00e5ff",
	accentViolet: "#a080ff",
	statusSuccess: "#3ed67b",
	statusWarn: "#ffb020",
	statusError: "#ff3b4b",
	dataviz: DEFAULT_DATAVIZ,
	fontMono:
		'"JetBrains Mono", "IBM Plex Mono", "Fira Code", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
	text10: 10,
	text11: 11,
	text12: 12,
	text14: 14,
};

function readVar(style: CSSStyleDeclaration, name: string, fallback: string): string {
	const raw = style.getPropertyValue(name).trim();
	return raw.length > 0 ? raw : fallback;
}

/**
 * Read current terminal tokens from `document.documentElement`.
 * Called inside `createTerminalChartOptions` so theme swaps are
 * reflected on the next chart option rebuild. On the server we
 * return the frozen default mirror.
 */
export function readTerminalTokens(): TerminalChartTokens {
	if (typeof document === "undefined") return DEFAULT_TOKENS;
	const style = getComputedStyle(document.documentElement);
	return {
		bgVoid: readVar(style, "--terminal-bg-void", DEFAULT_TOKENS.bgVoid),
		bgPanel: readVar(style, "--terminal-bg-panel", DEFAULT_TOKENS.bgPanel),
		bgPanelRaised: readVar(style, "--terminal-bg-panel-raised", DEFAULT_TOKENS.bgPanelRaised),
		fgPrimary: readVar(style, "--terminal-fg-primary", DEFAULT_TOKENS.fgPrimary),
		fgSecondary: readVar(style, "--terminal-fg-secondary", DEFAULT_TOKENS.fgSecondary),
		fgTertiary: readVar(style, "--terminal-fg-tertiary", DEFAULT_TOKENS.fgTertiary),
		fgMuted: readVar(style, "--terminal-fg-muted", DEFAULT_TOKENS.fgMuted),
		accentAmber: readVar(style, "--terminal-accent-amber", DEFAULT_TOKENS.accentAmber),
		accentCyan: readVar(style, "--terminal-accent-cyan", DEFAULT_TOKENS.accentCyan),
		accentViolet: readVar(style, "--terminal-accent-violet", DEFAULT_TOKENS.accentViolet),
		statusSuccess: readVar(style, "--terminal-status-success", DEFAULT_TOKENS.statusSuccess),
		statusWarn: readVar(style, "--terminal-status-warn", DEFAULT_TOKENS.statusWarn),
		statusError: readVar(style, "--terminal-status-error", DEFAULT_TOKENS.statusError),
		dataviz: [
			readVar(style, "--terminal-dataviz-1", DEFAULT_DATAVIZ[0]),
			readVar(style, "--terminal-dataviz-2", DEFAULT_DATAVIZ[1]),
			readVar(style, "--terminal-dataviz-3", DEFAULT_DATAVIZ[2]),
			readVar(style, "--terminal-dataviz-4", DEFAULT_DATAVIZ[3]),
			readVar(style, "--terminal-dataviz-5", DEFAULT_DATAVIZ[4]),
			readVar(style, "--terminal-dataviz-6", DEFAULT_DATAVIZ[5]),
			readVar(style, "--terminal-dataviz-7", DEFAULT_DATAVIZ[6]),
			readVar(style, "--terminal-dataviz-8", DEFAULT_DATAVIZ[7]),
		] as TerminalDatavizPalette,
		fontMono: readVar(style, "--terminal-font-mono", DEFAULT_TOKENS.fontMono),
		text10: DEFAULT_TOKENS.text10,
		text11: DEFAULT_TOKENS.text11,
		text12: DEFAULT_TOKENS.text12,
		text14: DEFAULT_TOKENS.text14,
	};
}

/** Inputs the caller provides — everything else is factory-owned. */
export interface TerminalChartOptionsInput {
	/** ECharts `series` array — the only thing most callers touch. */
	series: NonNullable<EChartsOption["series"]>;
	/** Optional `dataset` (preferred over per-series data for perf). */
	dataset?: EChartsOption["dataset"];
	/** Optional axis config (factory provides brutalist defaults). */
	xAxis?: EChartsOption["xAxis"];
	yAxis?: EChartsOption["yAxis"];
	/** Optional markArea (regime bands, stress windows). */
	markArea?: unknown;
	/**
	 * Choreo slot used for animation delay. Defaults to `primary`
	 * so a bare call renders a hero-style chart with 120ms delay.
	 */
	slot?: ChoreoSlot;
	/**
	 * Override the canvas renderer. Hero / heatmap / scatter charts
	 * use `canvas`; small sparklines use `svg`. The caller decides.
	 */
	renderer?: "canvas" | "svg";
	/** Show the x-axis tick labels. Default true. */
	showXAxisLabels?: boolean;
	/** Show the y-axis tick labels. Default true. */
	showYAxisLabels?: boolean;
	/** Show the legend. Default false — terminal charts rarely use it. */
	showLegend?: boolean;
	/** Optional visualMap config (heatmap). */
	visualMap?: EChartsOption["visualMap"];
	/** Optional dataZoom (time brush). */
	dataZoom?: EChartsOption["dataZoom"];
	/** Optional tooltip formatter override. */
	tooltipFormatter?: (params: unknown) => string;
	/** Disable animations entirely (e.g. for live sparklines). */
	disableAnimation?: boolean;
}

/**
 * Build a fully-wired ECharts option object. Callers should pass
 * only `series` (and optional `dataset`/axes/markArea/visualMap);
 * the factory owns everything else.
 */
export function createTerminalChartOptions(input: TerminalChartOptionsInput): EChartsOption {
	const tokens = readTerminalTokens();
	const reduced = prefersReducedMotion();
	const slot: ChoreoSlot = input.slot ?? "primary";
	const animate = !input.disableAnimation && !reduced;

	const mono = tokens.fontMono;
	const axisLabelStyle = {
		color: tokens.fgSecondary,
		fontFamily: mono,
		fontSize: tokens.text11,
		fontWeight: 400 as const,
	};
	const axisLineStyle = { lineStyle: { color: tokens.fgMuted, width: 1 } };
	const splitLineStyle = {
		lineStyle: {
			color: tokens.fgMuted,
			type: "dotted" as const,
			opacity: 0.5,
			width: 1,
		},
	};

	const baseXAxis = {
		type: "time" as const,
		axisLine: axisLineStyle,
		axisTick: { lineStyle: { color: tokens.fgMuted, width: 1 } },
		axisLabel: axisLabelStyle,
		splitLine: { show: false },
	};
	const baseYAxis = {
		type: "value" as const,
		axisLine: { show: false },
		axisTick: { show: false },
		axisLabel: axisLabelStyle,
		splitLine: splitLineStyle,
	};

	return {
		color: Array.from(tokens.dataviz),
		backgroundColor: "transparent",
		textStyle: { color: tokens.fgPrimary, fontFamily: mono, fontSize: tokens.text12 },
		animation: animate,
		animationDuration: terminalDuration.opening,
		animationDurationUpdate: terminalDuration.update,
		animationEasing: terminalEasing.cubicOut,
		animationEasingUpdate: terminalEasing.cubicOut,
		animationDelay: () => choreo[slot],
		grid: {
			left: 44,
			right: 16,
			top: 16,
			bottom: 24,
			containLabel: false,
			borderColor: tokens.fgMuted,
			borderWidth: 0,
		},
		tooltip: {
			trigger: "axis",
			backgroundColor: tokens.bgPanelRaised,
			borderColor: tokens.fgMuted,
			borderWidth: 1,
			borderRadius: 0,
			padding: [8, 12, 8, 12],
			textStyle: {
				color: tokens.fgPrimary,
				fontFamily: mono,
				fontSize: tokens.text11,
				fontWeight: 400,
			},
			axisPointer: {
				type: "cross",
				lineStyle: { color: tokens.accentAmber, width: 1, type: "solid" },
				crossStyle: { color: tokens.fgTertiary, width: 1, type: "dotted" },
				label: {
					backgroundColor: tokens.bgVoid,
					borderColor: tokens.accentAmber,
					borderWidth: 1,
					color: tokens.fgPrimary,
					fontFamily: mono,
					fontSize: tokens.text10,
					padding: [2, 6, 2, 6],
				},
			},
			extraCssText: "box-shadow: none; border-radius: 0;",
			confine: true,
			formatter: input.tooltipFormatter,
		},
		legend: input.showLegend
			? {
					show: true,
					textStyle: { color: tokens.fgSecondary, fontFamily: mono, fontSize: tokens.text11 },
					icon: "rect",
					itemWidth: 10,
					itemHeight: 2,
					itemGap: 16,
				}
			: { show: false },
		xAxis: applyXAxisDefaults(input.xAxis, baseXAxis, input.showXAxisLabels),
		yAxis: applyYAxisDefaults(input.yAxis, baseYAxis, input.showYAxisLabels),
		dataZoom: input.dataZoom,
		visualMap: input.visualMap,
		dataset: input.dataset,
		series: decorateSeries(input.series, input.markArea, animate),
	};
}

function applyXAxisDefaults(
	override: EChartsOption["xAxis"] | undefined,
	base: Record<string, unknown>,
	showLabels: boolean | undefined,
): EChartsOption["xAxis"] {
	if (showLabels === false) {
		(base as { axisLabel: { show?: boolean } }).axisLabel = { ...(base as { axisLabel: object }).axisLabel, show: false };
	}
	if (override === undefined) return base as EChartsOption["xAxis"];
	if (Array.isArray(override)) {
		return override.map((entry) => ({ ...base, ...entry })) as EChartsOption["xAxis"];
	}
	return { ...base, ...override } as EChartsOption["xAxis"];
}

function applyYAxisDefaults(
	override: EChartsOption["yAxis"] | undefined,
	base: Record<string, unknown>,
	showLabels: boolean | undefined,
): EChartsOption["yAxis"] {
	if (showLabels === false) {
		(base as { axisLabel: { show?: boolean } }).axisLabel = { ...(base as { axisLabel: object }).axisLabel, show: false };
	}
	if (override === undefined) return base as EChartsOption["yAxis"];
	if (Array.isArray(override)) {
		return override.map((entry) => ({ ...base, ...entry })) as EChartsOption["yAxis"];
	}
	return { ...base, ...override } as EChartsOption["yAxis"];
}

function decorateSeries(
	series: NonNullable<EChartsOption["series"]>,
	markArea: unknown,
	animate: boolean,
): NonNullable<EChartsOption["series"]> {
	const applyAnimation = (entry: Record<string, unknown>) => {
		if (!animate) {
			entry.animation = false;
			return entry;
		}
		entry.animationDuration = terminalDuration.opening;
		entry.animationDurationUpdate = terminalDuration.update;
		entry.animationEasing = terminalEasing.cubicOut;
		entry.animationEasingUpdate = terminalEasing.cubicOut;
		return entry;
	};
	const attach = (entry: Record<string, unknown>) => {
		if (markArea !== undefined && entry.markArea === undefined) {
			entry.markArea = markArea;
		}
		return applyAnimation(entry);
	};
	if (Array.isArray(series)) {
		return series.map((entry) => attach({ ...(entry as Record<string, unknown>) })) as NonNullable<
			EChartsOption["series"]
		>;
	}
	return attach({ ...(series as Record<string, unknown>) }) as NonNullable<EChartsOption["series"]>;
}
