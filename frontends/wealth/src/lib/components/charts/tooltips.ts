/**
 * ECharts tooltip formatters — Discovery FCL sprint (Phase 1.3)
 *
 * Centralized HTML tooltip builders that honor `ChartTokens` (colors +
 * Urbanist font). Use these on every chart on the standalone Analysis page
 * and the FCL col3 mini-charts so formatting stays consistent across Returns
 * & Risk, Holdings, and Peer groups.
 *
 * Formatter discipline: all numeric/date rendering routes through
 * `@netz/ui` helpers (`formatPercent`, `formatShortDate`). Never inline
 * `toFixed`/`toLocaleString`/`Intl.*` here — enforced by eslint.
 */

import { formatPercent, formatShortDate } from "@investintell/ui";
import type { ChartTokens } from "./chart-tokens";

type EChartsTooltipParam = {
	axisValue?: string | number | Date;
	seriesName?: string;
	value?: number | [unknown, number | null] | null;
	[key: string]: unknown;
};

/**
 * Tooltip formatter for NAV / return time series (percent-valued axis).
 * Renders one row per series with label (muted) + tabular value (strong).
 */
export function navTooltipFormatter(tokens: ChartTokens) {
	return (params: EChartsTooltipParam | EChartsTooltipParam[]): string => {
		const items = Array.isArray(params) ? params : [params];
		if (items.length === 0) return "";

		const axisValue = items[0]?.axisValue;
		const date = axisValue != null ? formatShortDate(new Date(axisValue as string)) : "";

		const rows = items
			.map((p) => {
				const label = p.seriesName ?? "";
				const raw = typeof p.value === "number" ? p.value : Array.isArray(p.value) ? p.value[1] : null;
				const formatted = raw == null ? "—" : formatPercent(raw, 2);
				return `<div style="display:flex;justify-content:space-between;gap:16px;font-variant-numeric:tabular-nums">
					<span style="color:${tokens.axisLabel}">${label}</span>
					<strong>${formatted}</strong>
				</div>`;
			})
			.join("");

		return `<div style="font-family:${tokens.fontFamily};font-size:12px;padding:4px 2px">
			<div style="color:${tokens.axisLabel};margin-bottom:6px">${date}</div>
			${rows}
		</div>`;
	};
}
