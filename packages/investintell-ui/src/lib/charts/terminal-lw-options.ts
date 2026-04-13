/**
 * Netz Wealth OS -- createTerminalLightweightChartOptions()
 * =========================================================
 *
 * Mirrors `createTerminalChartOptions()` but for lightweight-charts v5
 * API. Reads CSS custom properties from `tokens/terminal.css` via
 * `readTerminalTokens()` (already exists in terminal-options.ts).
 *
 * Replaces ~45 hardcoded hex values across TerminalPriceChart and
 * TerminalResearchChart with a single factory call.
 *
 * Contract:
 *   - ZERO hex literals (only SSR fallbacks in readTerminalTokens).
 *   - Returns DeepPartial<ChartOptions> from lightweight-charts.
 *   - Callers spread the result into createChart() options.
 */

import { readTerminalTokens, type TerminalChartTokens } from "./terminal-options.js";

/**
 * Structural subset of lightweight-charts ChartOptions.
 *
 * Defined inline to avoid a dependency on `lightweight-charts` from
 * `@investintell/ui` — that package lives only in `frontends/wealth/`.
 * TypeScript structural typing ensures callers in the wealth frontend
 * can spread this directly into `createChart()` without casts.
 */
export interface TerminalLWChartOptions {
	layout?: {
		background?: { color?: string };
		textColor?: string;
		fontFamily?: string;
		fontSize?: number;
	};
	grid?: {
		vertLines?: { color?: string };
		horzLines?: { color?: string };
	};
	crosshair?: {
		vertLine?: { color?: string; labelBackgroundColor?: string };
		horzLine?: { color?: string; labelBackgroundColor?: string };
	};
	rightPriceScale?: {
		borderVisible?: boolean;
		scaleMargins?: { top: number; bottom: number };
		mode?: number;
	};
	timeScale?: {
		borderColor?: string;
		timeVisible?: boolean;
		secondsVisible?: boolean;
		rightOffset?: number;
	};
	handleScroll?: boolean;
	handleScale?: boolean;
}

export interface TerminalLWChartOptionsInput {
	/**
	 * Whether to show time labels on the time scale.
	 * Default: false (most panes suppress time labels; only bottom pane shows).
	 */
	timeVisible?: boolean;
	/**
	 * Whether to show seconds on the time scale. Default: false.
	 */
	secondsVisible?: boolean;
	/**
	 * Right offset for the time scale (bar count). Default: 5.
	 */
	rightOffset?: number;
	/**
	 * Price scale mode. Pass lc.PriceScaleMode.Percentage for overlay charts.
	 * Default: undefined (normal mode).
	 */
	priceScaleMode?: number;
	/**
	 * Scale margins for the right price scale.
	 * Default: { top: 0.08, bottom: 0.08 }.
	 */
	scaleMargins?: { top: number; bottom: number };
	/**
	 * Crosshair color. Defaults to terminal accent amber.
	 * Pass a specific token color for per-pane crosshair theming.
	 */
	crosshairColor?: string;
	/**
	 * Font size override. Default: 10 (matches terminal-text-10).
	 */
	fontSize?: number;
}

/**
 * Build lightweight-charts ChartOptions from terminal tokens.
 *
 * Usage:
 * ```ts
 * const lc = await import("lightweight-charts");
 * const opts = createTerminalLightweightChartOptions({ timeVisible: true });
 * const chart = lc.createChart(container, { autoSize: true, ...opts });
 * ```
 */
export function createTerminalLightweightChartOptions(
	input: TerminalLWChartOptionsInput = {},
): TerminalLWChartOptions {
	const t: TerminalChartTokens = readTerminalTokens();

	const crosshairColor = input.crosshairColor ?? t.accentAmber;
	const crosshairAlpha = hexToRgba(crosshairColor, 0.3);
	const gridColor = hexToRgba(t.fgMuted, 0.15);
	const borderColor = hexToRgba(t.fgMuted, 0.3);

	return {
		layout: {
			background: { color: "transparent" },
			textColor: t.fgTertiary,
			fontFamily: t.fontMono,
			fontSize: input.fontSize ?? t.text10,
		},
		grid: {
			vertLines: { color: gridColor },
			horzLines: { color: gridColor },
		},
		crosshair: {
			vertLine: {
				color: crosshairAlpha,
				labelBackgroundColor: crosshairColor,
			},
			horzLine: {
				color: crosshairAlpha,
				labelBackgroundColor: crosshairColor,
			},
		},
		rightPriceScale: {
			borderVisible: false,
			scaleMargins: input.scaleMargins ?? { top: 0.08, bottom: 0.08 },
			...(input.priceScaleMode !== undefined ? { mode: input.priceScaleMode } : {}),
		},
		timeScale: {
			borderColor,
			timeVisible: input.timeVisible ?? false,
			secondsVisible: input.secondsVisible ?? false,
			rightOffset: input.rightOffset ?? 5,
		},
		handleScroll: true,
		handleScale: true,
	};
}

/**
 * Terminal-themed series defaults for lightweight-charts.
 *
 * Callers use these instead of hardcoded hex in addSeries() options.
 */
export function terminalLWSeriesColors(tokens?: TerminalChartTokens) {
	const t = tokens ?? readTerminalTokens();
	return {
		/** Baseline series (instrument price): cyan primary. */
		baseline: {
			topLineColor: t.accentCyan,
			topFillColor1: hexToRgba(t.accentCyan, 0.10),
			topFillColor2: hexToRgba(t.accentCyan, 0.01),
			bottomLineColor: t.statusError,
			bottomFillColor1: hexToRgba(t.statusError, 0.01),
			bottomFillColor2: hexToRgba(t.statusError, 0.06),
			priceLineColor: hexToRgba(t.accentCyan, 0.4),
		},
		/** NAV overlay line: amber/gold. */
		navOverlay: {
			color: t.accentAmber,
		},
		/** Drawdown baseline: error red. */
		drawdown: {
			topLineColor: "rgba(0, 0, 0, 0)",
			topFillColor1: "rgba(0, 0, 0, 0)",
			topFillColor2: "rgba(0, 0, 0, 0)",
			bottomLineColor: t.statusError,
			bottomFillColor1: hexToRgba(t.statusError, 0.20),
			bottomFillColor2: hexToRgba(t.statusError, 0.02),
		},
		/** Volatility line: violet. */
		volatility: {
			color: t.accentViolet,
		},
		/** Regime probability area: amber. */
		regime: {
			topColor: hexToRgba(t.accentAmber, 0.30),
			bottomColor: hexToRgba(t.accentAmber, 0.02),
			lineColor: t.accentAmber,
		},
	};
}

/**
 * Convert a hex color to rgba string. Handles 3, 6, and 8-char hex.
 * Falls back to the raw color string if parsing fails.
 */
function hexToRgba(hex: string, alpha: number): string {
	const cleaned = hex.replace("#", "");
	let r: number, g: number, b: number;

	if (cleaned.length === 3) {
		r = parseInt(cleaned[0]! + cleaned[0], 16);
		g = parseInt(cleaned[1]! + cleaned[1], 16);
		b = parseInt(cleaned[2]! + cleaned[2], 16);
	} else if (cleaned.length >= 6) {
		r = parseInt(cleaned.substring(0, 2), 16);
		g = parseInt(cleaned.substring(2, 4), 16);
		b = parseInt(cleaned.substring(4, 6), 16);
	} else {
		return hex; // fallback
	}

	if (isNaN(r) || isNaN(g) || isNaN(b)) return hex;
	return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}
