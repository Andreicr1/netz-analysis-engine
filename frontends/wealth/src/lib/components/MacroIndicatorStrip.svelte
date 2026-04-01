<!--
  Macro Indicator Strip — 4 KPI chips for VIX, Yield Curve, CPI, Fed Funds.
  Data from riskStore.macroIndicators (GET /risk/macro).
-->
<script lang="ts">
	import { formatNumber, formatPercent, formatShortDate } from "@investintell/ui";

	interface Props {
		indicators: {
			vix?: number | null;
			vix_date?: string | null;
			yield_curve_10y2y?: number | null;
			yield_curve_date?: string | null;
			cpi_yoy?: number | null;
			cpi_date?: string | null;
			fed_funds_rate?: number | null;
			fed_funds_date?: string | null;
		} | null;
	}

	let { indicators }: Props = $props();

	function vixColor(v: number | null | undefined): string {
		if (v == null) return "var(--ii-text-muted)";
		if (v > 30) return "var(--ii-danger)";
		if (v > 20) return "var(--ii-warning)";
		return "var(--ii-success)";
	}

	function yieldCurveColor(v: number | null | undefined): string {
		if (v == null) return "var(--ii-text-muted)";
		if (v < 0) return "var(--ii-danger)";
		return "var(--ii-text-primary)";
	}
</script>

{#if indicators}
	<div class="macro-strip">
		<div class="macro-chip" title={indicators.vix_date ? `As of ${formatShortDate(indicators.vix_date)}` : ""}>
			<span class="macro-label">VIX</span>
			<span class="macro-value" style:color={vixColor(indicators.vix)}>
				{indicators.vix != null ? formatNumber(indicators.vix, 1) : "—"}
			</span>
		</div>
		<div class="macro-chip" title={indicators.yield_curve_date ? `As of ${formatShortDate(indicators.yield_curve_date)}` : ""}>
			<span class="macro-label">10Y-2Y</span>
			<span class="macro-value" style:color={yieldCurveColor(indicators.yield_curve_10y2y)}>
				{indicators.yield_curve_10y2y != null ? formatNumber(indicators.yield_curve_10y2y, 2) + "%" : "—"}
			</span>
		</div>
		<div class="macro-chip" title={indicators.cpi_date ? `As of ${formatShortDate(indicators.cpi_date)}` : ""}>
			<span class="macro-label">CPI YoY</span>
			<span class="macro-value">
				{indicators.cpi_yoy != null ? formatPercent(indicators.cpi_yoy / 100) : "—"}
			</span>
		</div>
		<div class="macro-chip" title={indicators.fed_funds_date ? `As of ${formatShortDate(indicators.fed_funds_date)}` : ""}>
			<span class="macro-label">Fed Funds</span>
			<span class="macro-value">
				{indicators.fed_funds_rate != null ? formatPercent(indicators.fed_funds_rate / 100) : "—"}
			</span>
		</div>
	</div>
{/if}

<style>
	.macro-strip {
		display: flex;
		gap: 8px;
		flex-wrap: wrap;
	}

	.macro-chip {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 4px 10px;
		background: var(--ii-surface-alt);
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 6px);
		cursor: help;
	}

	.macro-label {
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.3px;
		color: var(--ii-text-muted);
	}

	.macro-value {
		font-size: 13px;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-primary);
	}
</style>
