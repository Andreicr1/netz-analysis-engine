<!--
  NarrativeMetricsStrip — sticky right-column metrics strip for the
  ConstructionNarrative panel.

  Renders the 4 institutional ex-ante metrics (expected return,
  volatility, CVaR 95%, Sharpe) with optional delta badges from
  ``ex_ante_vs_previous``. Every number routes through
  @investintell/ui formatters (DL16).
-->
<script lang="ts">
	import { formatPercent, formatNumber } from "@investintell/ui";

	interface Props {
		metrics: Record<string, number | null> | null;
		deltas?: Record<string, number | null> | null;
	}

	let { metrics, deltas }: Props = $props();

	interface Metric {
		key: string;
		label: string;
		format: "percent" | "ratio" | "raw";
		digits: number;
		invert?: boolean; // lower is better (CVaR, vol)
	}

	const METRICS: readonly Metric[] = [
		{ key: "expected_return", label: "Expected return", format: "percent", digits: 2 },
		{ key: "portfolio_volatility", label: "Volatility", format: "percent", digits: 2, invert: true },
		{ key: "cvar_95", label: "Tail loss (95%)", format: "percent", digits: 2, invert: true },
		{ key: "sharpe_ratio", label: "Risk-adjusted return", format: "ratio", digits: 2 },
	];

	function formatValue(value: number | null | undefined, m: Metric): string {
		if (value === null || value === undefined) return "—";
		switch (m.format) {
			case "percent":
				return formatPercent(value, m.digits);
			case "ratio":
				return formatNumber(value, m.digits);
			case "raw":
			default:
				return formatNumber(value, m.digits);
		}
	}

	function formatDelta(value: number | null | undefined, m: Metric): string {
		if (value === null || value === undefined) return "";
		const sign = value > 0 ? "+" : "";
		const body =
			m.format === "percent" ? formatPercent(value, m.digits) : formatNumber(value, m.digits);
		return `${sign}${body}`;
	}

	function deltaAccent(value: number | null | undefined, m: Metric): "up" | "down" | "flat" {
		if (value === null || value === undefined || value === 0) return "flat";
		const isImprovement = m.invert ? value < 0 : value > 0;
		return isImprovement ? "up" : "down";
	}
</script>

<aside class="nms-root">
	<header class="nms-header">
		<span class="nms-kicker">Ex-ante</span>
		<span class="nms-title">Key metrics</span>
	</header>
	<ul class="nms-list">
		{#each METRICS as m (m.key)}
			{@const raw = metrics?.[m.key] ?? null}
			{@const delta = deltas?.[m.key] ?? null}
			{@const accent = deltaAccent(delta, m)}
			<li class="nms-row">
				<span class="nms-label">{m.label}</span>
				<span class="nms-value">{formatValue(raw, m)}</span>
				{#if delta !== null}
					<span class="nms-delta" data-accent={accent}>{formatDelta(delta, m)}</span>
				{/if}
			</li>
		{/each}
	</ul>
</aside>

<style>
	.nms-root {
		display: flex;
		flex-direction: column;
		gap: 14px;
		padding: 16px;
		background: rgba(255, 255, 255, 0.02);
		border: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
		border-radius: 8px;
		position: sticky;
		top: 16px;
		font-family: "Urbanist", system-ui, sans-serif;
	}
	.nms-header {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.nms-kicker {
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--ii-text-muted, #85a0bd);
	}
	.nms-title {
		font-size: 13px;
		font-weight: 700;
		color: var(--ii-text-primary, #ffffff);
	}
	.nms-list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 10px;
	}
	.nms-row {
		display: grid;
		grid-template-columns: 1fr auto auto;
		align-items: baseline;
		gap: 8px;
	}
	.nms-label {
		font-size: 11px;
		color: var(--ii-text-muted, #85a0bd);
	}
	.nms-value {
		font-size: 14px;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-primary, #ffffff);
	}
	.nms-delta {
		font-size: 11px;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-muted, #85a0bd);
	}
	.nms-delta[data-accent="up"] {
		color: var(--ii-success, #3fb950);
	}
	.nms-delta[data-accent="down"] {
		color: var(--ii-danger, #fc1a1a);
	}
</style>
