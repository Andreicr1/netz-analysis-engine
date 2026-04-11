/*
 * tests/terminal-options.test.ts
 * ==============================
 *
 * Source of truth: docs/plans/2026-04-11-terminal-unification-master-plan.md §1.2
 *
 * Contract tests for `createTerminalChartOptions()` — the single
 * factory that owns the brutalist ECharts aesthetic across every
 * surface under `(terminal)/`. Pattern wrappers (TerminalLineChart,
 * TerminalHeatmap, TerminalTreemap, …) compose this; if it drifts
 * the entire visual register drifts in lockstep.
 *
 * What we lock:
 *   1. Brutalist grid integrity — zero radii, hairline borders,
 *      transparent panel background, monospace typography, dotted
 *      split lines, fixed grid padding.
 *   2. Eight-slot ordinal palette length and presence in the
 *      `color` array of every output (no truncation, no shuffle).
 *   3. Choreo slot wiring — the `animationDelay` callback returns
 *      the canonical delay for each slot.
 *   4. Density flags — `showXAxisLabels` / `showYAxisLabels` /
 *      `showLegend` toggle the visible chrome without leaking
 *      caller-provided overrides into the base axis style.
 *   5. Live mode — `disableAnimation: true` forces animation off
 *      on the chart AND on every series entry, so 60s tickers do
 *      not pay the entrance reveal cost.
 *   6. Series decoration — markArea propagation, animation flags
 *      are layered on regardless of whether `series` is a single
 *      object or an array.
 *
 * The factory is SSR-aware. happy-dom provides `document` and
 * `getComputedStyle`, but the empty stylesheet means every
 * `readVar` falls through to its DEFAULT_TOKENS mirror — which is
 * exactly what we want to assert against.
 */

import { describe, it, expect } from "vitest";
import {
	createTerminalChartOptions,
	readTerminalTokens,
} from "../src/lib/charts/terminal-options.js";
import { choreo } from "../src/lib/charts/choreo.js";
import type { EChartsOption } from "echarts";

const baseSeries = [
	{
		type: "line" as const,
		data: [
			[1, 100],
			[2, 110],
			[3, 105],
		],
	},
];

function build(overrides: Partial<Parameters<typeof createTerminalChartOptions>[0]> = {}) {
	return createTerminalChartOptions({ series: baseSeries, ...overrides });
}

describe("readTerminalTokens — SSR fallback mirror", () => {
	it("returns the eight-slot dataviz palette regardless of stylesheet state", () => {
		const tokens = readTerminalTokens();
		expect(tokens.dataviz).toHaveLength(8);
		for (const color of tokens.dataviz) {
			expect(typeof color).toBe("string");
			expect(color.length).toBeGreaterThan(0);
		}
	});

	it("exposes the four numeric text scale tiers", () => {
		const tokens = readTerminalTokens();
		expect(tokens.text10).toBe(10);
		expect(tokens.text11).toBe(11);
		expect(tokens.text12).toBe(12);
		expect(tokens.text14).toBe(14);
	});
});

describe("createTerminalChartOptions — brutalist grid integrity", () => {
	it("paints a transparent background so the panel cage shows through", () => {
		const opt = build();
		expect(opt.backgroundColor).toBe("transparent");
	});

	it("locks zero-radius square tooltips with hairline borders", () => {
		const opt = build();
		const tooltip = opt.tooltip as Record<string, unknown>;
		expect(tooltip.borderRadius).toBe(0);
		expect(tooltip.borderWidth).toBe(1);
		expect(typeof tooltip.borderColor).toBe("string");
		expect(String(tooltip.extraCssText)).toMatch(/border-radius:\s*0/);
		expect(String(tooltip.extraCssText)).toMatch(/box-shadow:\s*none/);
	});

	it("uses a fixed grid (44/16/16/24) with no border weight", () => {
		const opt = build();
		const grid = opt.grid as Record<string, unknown>;
		expect(grid.left).toBe(44);
		expect(grid.right).toBe(16);
		expect(grid.top).toBe(16);
		expect(grid.bottom).toBe(24);
		expect(grid.containLabel).toBe(false);
		expect(grid.borderWidth).toBe(0);
	});

	it("forces dotted split lines on the y-axis (terminal grid look)", () => {
		const opt = build();
		const yAxis = opt.yAxis as Record<string, unknown>;
		const splitLine = yAxis.splitLine as { lineStyle: { type: string } };
		expect(splitLine.lineStyle.type).toBe("dotted");
	});

	it("hides the y-axis line and ticks (only the dotted grid remains)", () => {
		const opt = build();
		const yAxis = opt.yAxis as Record<string, unknown>;
		expect((yAxis.axisLine as { show: boolean }).show).toBe(false);
		expect((yAxis.axisTick as { show: boolean }).show).toBe(false);
	});

	it("uses time-type x-axis by default", () => {
		const opt = build();
		const xAxis = opt.xAxis as Record<string, unknown>;
		expect(xAxis.type).toBe("time");
	});

	it("renders text in a monospace stack across textStyle and tooltip", () => {
		const opt = build();
		const textStyle = opt.textStyle as { fontFamily: string };
		const tooltip = opt.tooltip as { textStyle: { fontFamily: string } };
		expect(textStyle.fontFamily).toMatch(/Mono|mono|Consolas/);
		expect(tooltip.textStyle.fontFamily).toMatch(/Mono|mono|Consolas/);
	});
});

describe("createTerminalChartOptions — eight-slot palette", () => {
	it("emits the dataviz palette as the chart `color` array, length 8", () => {
		const opt = build();
		expect(Array.isArray(opt.color)).toBe(true);
		expect((opt.color as string[]).length).toBe(8);
	});

	it("preserves palette ordering between readTerminalTokens and the option output", () => {
		const tokens = readTerminalTokens();
		const opt = build();
		expect(opt.color).toEqual(Array.from(tokens.dataviz));
	});
});

describe("createTerminalChartOptions — choreo slot wiring", () => {
	const slots = ["chrome", "primary", "secondary", "tail", "ambient"] as const;

	for (const slot of slots) {
		it(`slot="${slot}" → animationDelay callback returns ${choreo[slot]}ms`, () => {
			const opt = build({ slot });
			const delayFn = opt.animationDelay as (idx: number) => number;
			expect(typeof delayFn).toBe("function");
			expect(delayFn(0)).toBe(choreo[slot]);
			expect(delayFn(7)).toBe(choreo[slot]);
		});
	}

	it("defaults to the `primary` slot (hero behavior) when no slot is provided", () => {
		const opt = build();
		const delayFn = opt.animationDelay as (idx: number) => number;
		expect(delayFn(0)).toBe(choreo.primary);
	});
});

describe("createTerminalChartOptions — density flags", () => {
	it("hides the legend by default (terminal charts rarely use one)", () => {
		const opt = build();
		expect((opt.legend as { show: boolean }).show).toBe(false);
	});

	it("shows the legend when showLegend=true and styles it as monospace rectangles", () => {
		const opt = build({ showLegend: true });
		const legend = opt.legend as Record<string, unknown>;
		expect(legend.show).toBe(true);
		expect(legend.icon).toBe("rect");
		expect((legend.textStyle as { fontFamily: string }).fontFamily).toMatch(/Mono|mono|Consolas/);
	});

	it("hides x-axis tick labels when showXAxisLabels=false (compact density)", () => {
		const opt = build({ showXAxisLabels: false });
		const xAxis = opt.xAxis as { axisLabel: { show: boolean } };
		expect(xAxis.axisLabel.show).toBe(false);
	});

	it("hides y-axis tick labels when showYAxisLabels=false (compact density)", () => {
		const opt = build({ showYAxisLabels: false });
		const yAxis = opt.yAxis as { axisLabel: { show: boolean } };
		expect(yAxis.axisLabel.show).toBe(false);
	});

	it("preserves caller-provided x-axis overrides on top of brutalist defaults", () => {
		const opt = build({
			xAxis: { type: "category" as const, data: ["Q1", "Q2", "Q3"] },
		});
		const xAxis = opt.xAxis as Record<string, unknown>;
		expect(xAxis.type).toBe("category");
		expect((xAxis as { data: string[] }).data).toEqual(["Q1", "Q2", "Q3"]);
		// Brutalist axisLine survives the merge.
		expect(xAxis.axisLine).toBeDefined();
	});
});

describe("createTerminalChartOptions — live mode (disableAnimation)", () => {
	it("disables top-level animation when disableAnimation=true (live ticker)", () => {
		const opt = build({ disableAnimation: true });
		expect(opt.animation).toBe(false);
	});

	it("disables animation on every series entry when disableAnimation=true", () => {
		const opt = build({
			series: [
				{ type: "line" as const, data: [[1, 1]] },
				{ type: "bar" as const, data: [[1, 2]] },
				{ type: "scatter" as const, data: [[1, 3]] },
			],
			disableAnimation: true,
		});
		const series = opt.series as Array<{ animation?: boolean }>;
		expect(series).toHaveLength(3);
		for (const s of series) {
			expect(s.animation).toBe(false);
		}
	});

	it("enables animation on every series entry by default", () => {
		const opt = build();
		const series = opt.series as Array<Record<string, unknown>>;
		for (const s of series) {
			expect(s.animationDuration).toBeDefined();
			expect(s.animationEasing).toBe("cubicOut");
		}
	});
});

describe("createTerminalChartOptions — series decoration", () => {
	it("propagates markArea onto every series entry that does not already define one", () => {
		const markArea = { itemStyle: { color: "rgba(255, 176, 32, 0.08)" }, data: [] };
		const opt = build({
			series: [
				{ type: "line" as const, data: [[1, 1]] },
				{ type: "line" as const, data: [[1, 2]] },
			],
			markArea,
		});
		const series = opt.series as Array<{ markArea?: unknown }>;
		expect(series[0].markArea).toBe(markArea);
		expect(series[1].markArea).toBe(markArea);
	});

	it("does not overwrite a markArea that the series already supplies", () => {
		const factoryMarkArea = { itemStyle: { color: "amber" } };
		const seriesMarkArea = { itemStyle: { color: "violet" } };
		const opt = build({
			series: [{ type: "line" as const, data: [[1, 1]], markArea: seriesMarkArea }],
			markArea: factoryMarkArea,
		});
		const series = opt.series as Array<{ markArea?: unknown }>;
		expect(series[0].markArea).toBe(seriesMarkArea);
	});

	it("accepts a single series object (not an array) and decorates it", () => {
		const opt = createTerminalChartOptions({
			series: { type: "line", data: [[1, 1]] } as unknown as NonNullable<EChartsOption["series"]>,
		});
		const series = opt.series as Record<string, unknown>;
		expect(Array.isArray(series)).toBe(false);
		expect(series.type).toBe("line");
		expect(series.animationEasing).toBe("cubicOut");
	});

	it("forwards optional dataset / visualMap / dataZoom verbatim", () => {
		const dataset = { source: [[1, 2]] };
		const visualMap = { min: 0, max: 100 };
		const dataZoom = [{ type: "inside" as const, start: 0, end: 100 }];
		const opt = build({ dataset, visualMap, dataZoom });
		expect(opt.dataset).toBe(dataset);
		expect(opt.visualMap).toBe(visualMap);
		expect(opt.dataZoom).toBe(dataZoom);
	});
});
