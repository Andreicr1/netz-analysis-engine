import * as echarts from "echarts/core";
import {
	LineChart,
	BarChart as EBarChart,
	ScatterChart,
	GaugeChart,
	FunnelChart,
	HeatmapChart,
	GraphChart,
	TreemapChart,
	SunburstChart,
} from "echarts/charts";
import {
	GridComponent,
	TooltipComponent,
	LegendComponent,
	DataZoomComponent,
	VisualMapComponent,
	MarkLineComponent,
	MarkAreaComponent,
	ToolboxComponent,
	TitleComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([
	LineChart,
	EBarChart,
	ScatterChart,
	GaugeChart,
	FunnelChart,
	HeatmapChart,
	GraphChart,
	TreemapChart,
	SunburstChart,
	GridComponent,
	TooltipComponent,
	LegendComponent,
	DataZoomComponent,
	VisualMapComponent,
	MarkLineComponent,
	MarkAreaComponent,
	ToolboxComponent,
	TitleComponent,
	CanvasRenderer,
]);

/** Read CSS custom properties for chart theming. */
function readCSSTokens(): Record<string, string> {
	if (typeof document === "undefined") return {};
	const style = getComputedStyle(document.documentElement);
	const get = (name: string) => style.getPropertyValue(name).trim();
	return {
		surface: get("--netz-surface") || "#ffffff",
		surfaceAlt: get("--netz-surface-alt") || "#f8fafc",
		surfaceElevated: get("--netz-surface-elevated") || "#ffffff",
		border: get("--netz-border") || "#e2e8f0",
		textPrimary: get("--netz-text-primary") || "#0f172a",
		textSecondary: get("--netz-text-secondary") || "#475569",
		textMuted: get("--netz-text-muted") || "#94a3b8",
		chart1: get("--netz-chart-1") || "#1b365d",
		chart2: get("--netz-chart-2") || "#3a7bd5",
		chart3: get("--netz-chart-3") || "#ff975a",
		chart4: get("--netz-chart-4") || "#8b9daf",
		chart5: get("--netz-chart-5") || "#d4e4f7",
	};
}

/** Build and register the global Netz ECharts theme from CSS tokens. */
function registerNetzTheme(): void {
	const t = readCSSTokens();
	echarts.registerTheme("netz-theme", {
		color: [t.chart1, t.chart2, t.chart3, t.chart4, t.chart5],
		backgroundColor: "transparent",
		textStyle: { color: t.textPrimary },
		title: { textStyle: { color: t.textPrimary }, subtextStyle: { color: t.textSecondary } },
		legend: { textStyle: { color: t.textSecondary } },
		tooltip: {
			backgroundColor: t.surfaceElevated,
			borderColor: t.border,
			textStyle: { color: t.textPrimary },
		},
		categoryAxis: {
			axisLine: { lineStyle: { color: t.border } },
			axisTick: { lineStyle: { color: t.border } },
			axisLabel: { color: t.textSecondary },
			splitLine: { lineStyle: { color: t.border, type: "dashed" } },
		},
		valueAxis: {
			axisLine: { lineStyle: { color: t.border } },
			axisTick: { lineStyle: { color: t.border } },
			axisLabel: { color: t.textSecondary },
			splitLine: { lineStyle: { color: t.border, type: "dashed" } },
		},
	});
}

/** Initialize theme once. Observe data-theme changes on <html> to re-register. */
let _initialized = false;
function initTheme(): void {
	if (_initialized || typeof document === "undefined") return;
	_initialized = true;

	registerNetzTheme();

	// Re-register on theme attribute change
	const observer = new MutationObserver((mutations) => {
		for (const m of mutations) {
			if (m.attributeName === "data-theme") {
				registerNetzTheme();
			}
		}
	});
	observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
}

// Auto-init on import (browser only)
if (typeof document !== "undefined") {
	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", initTheme, { once: true });
	} else {
		initTheme();
	}
}

/**
 * Global chart options per Wealth Frontend UX Principles.
 * Merge these into every chart's option object.
 */
export const globalChartOptions = {
	animation: true,
	animationDuration: 300,
	backgroundColor: "transparent",
	textStyle: { fontFamily: "Inter, system-ui, sans-serif", fontSize: 12 },
	grid: { containLabel: true, left: 8, right: 8, top: 8, bottom: 8 },
	tooltip: {
		trigger: "axis" as const,
		axisPointer: { type: "cross" as const },
		confine: true,
	},
	toolbox: {
		show: true,
		feature: {
			dataZoom: { show: true },
			restore: { show: true },
			saveAsImage: { show: true, name: "netz-chart" },
		},
	},
};

/** Sparkline options — no grid, no axes, no tooltip, no toolbox. Pure shape. */
export const sparklineOptions = {
	animation: false,
	backgroundColor: "transparent",
	grid: { show: false, left: 0, right: 0, top: 0, bottom: 0 },
	xAxis: { show: false, type: "time" as const },
	yAxis: { show: false },
	tooltip: { show: false },
	toolbox: { show: false },
};

/** Regime color mapping per UX spec. */
export const regimeColors: Record<string, string> = {
	RISK_ON: "#3b82f6",
	RISK_OFF: "#f59e0b",
	INFLATION: "#f97316",
	CRISIS: "#ef4444",
};

/** Status colors per UX spec. */
export const statusColors = {
	ok: "#22c55e",
	warning: "#f59e0b",
	breach: "#ef4444",
	neutral: "#6b7280",
};

export { echarts, initTheme, registerNetzTheme };
export type { EChartsOption } from "echarts";
