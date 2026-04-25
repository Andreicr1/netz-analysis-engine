<!--
  /research/[instrumentId] — Factor Exposure Surface (PR-Q8B)

  Renders the 6 Kelly-Pruitt-Su style biases + 8 market sensitivities
  for any fund in the terminal catalog, plus cross-sectional peer scatter.

  Layout: 3-panel terminal grid (style bias radar | sensitivities bar | stats)
  + full-width scatter below.
-->
<script lang="ts">
	import { invalidateAll } from "$app/navigation";
	import { PanelErrorState } from "@investintell/ui/runtime";
	import { formatNumber, formatPercent, formatDate } from "@investintell/ui";
	import StyleBiasRadar from "@investintell/ii-terminal-core/components/research/StyleBiasRadar.svelte";
	import MarketSensitivitiesBar from "@investintell/ii-terminal-core/components/research/MarketSensitivitiesBar.svelte";
	import RiskReturnScatter from "@investintell/ii-terminal-core/components/research/RiskReturnScatter.svelte";
	import type {
		SingleFundResearchResponse,
		ResearchScatterResponse,
	} from "@investintell/ii-terminal-core/types/research";

	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();

	const research = $derived(data.research.data);
	const researchErr = $derived(data.research.error);
	const scatter = $derived(data.scatter.data);
	const scatterErr = $derived(data.scatter.error);

	const ticker = $derived(research?.ticker ?? "—");
	const name = $derived(research?.instrument_name ?? "Unknown Fund");
	const styleBiasDate = $derived(research?.style_bias.as_of_date ?? null);
	const sensitivitiesDate = $derived(research?.market_sensitivities.as_of_date ?? null);

	const rSquared = $derived(research?.market_sensitivities.r_squared ?? null);
	const systematicPct = $derived(research?.market_sensitivities.systematic_risk_pct ?? null);

	function fmtAsOf(date: string | null): string {
		if (!date) return "—";
		return formatDate(date, "short");
	}
</script>

<div class="fe-root">
	{#if researchErr}
		<div class="fe-error-wrap">
			<PanelErrorState
				title="Research data unavailable"
				message={researchErr.message}
				onRetry={researchErr.recoverable ? () => invalidateAll() : undefined}
			/>
		</div>
	{:else if research}
		<div class="fe-header">
			<div class="fe-header-left">
				<span class="fe-ticker">{ticker}</span>
				<span class="fe-name">{name}</span>
			</div>
			<div class="fe-header-right">
				<span class="fe-as-of">as of {fmtAsOf(styleBiasDate)}</span>
			</div>
		</div>

		<div class="fe-grid">
			<div class="fe-panel fe-panel--bias">
				<StyleBiasRadar exposures={research.style_bias.exposures} />
			</div>

			<div class="fe-panel fe-panel--sens">
				<MarketSensitivitiesBar
					exposures={research.market_sensitivities.exposures}
				/>
			</div>

			<div class="fe-panel fe-panel--stats">
				<div class="fe-stats-card">
					<h2>Factor Stats</h2>
					<div class="fe-stats-grid">
						<div class="fe-stat">
							<span class="fe-stat-label">R-Squared</span>
							<span class="fe-stat-value">
								{rSquared != null ? formatNumber(rSquared, 3) : "—"}
							</span>
						</div>
						<div class="fe-stat">
							<span class="fe-stat-label">Systematic Risk</span>
							<span class="fe-stat-value">
								{systematicPct != null ? formatPercent(systematicPct / 100, 1) : "—"}
							</span>
						</div>
						<div class="fe-stat">
							<span class="fe-stat-label">Style Factors</span>
							<span class="fe-stat-value">
								{research.style_bias.exposures.length}
							</span>
						</div>
						<div class="fe-stat">
							<span class="fe-stat-label">Market Factors</span>
							<span class="fe-stat-value">
								{research.market_sensitivities.exposures.length}
							</span>
						</div>
						<div class="fe-stat">
							<span class="fe-stat-label">Style Date</span>
							<span class="fe-stat-value fe-stat-value--date">
								{fmtAsOf(styleBiasDate)}
							</span>
						</div>
						<div class="fe-stat">
							<span class="fe-stat-label">Sensitivities Date</span>
							<span class="fe-stat-value fe-stat-value--date">
								{fmtAsOf(sensitivitiesDate)}
							</span>
						</div>
					</div>

					{#if research.style_bias.exposures.length > 0}
						<div class="fe-legend">
							<h3>Significance</h3>
							<div class="fe-legend-items">
								<span class="fe-legend-dot fe-legend-dot--high">High</span>
								<span class="fe-legend-dot fe-legend-dot--medium">Medium</span>
								<span class="fe-legend-dot fe-legend-dot--low">Low</span>
								<span class="fe-legend-dot fe-legend-dot--none">None</span>
							</div>
						</div>
					{/if}
				</div>
			</div>
		</div>

		<div class="fe-scatter-wrap">
			<svelte:boundary>
				{#if scatterErr}
					<div class="fe-scatter-empty">
						{scatterErr.message}
					</div>
				{:else if scatter}
					<RiskReturnScatter payload={scatter} />
				{:else}
					<div class="fe-scatter-empty">No cross-sectional data available.</div>
				{/if}
				{#snippet failed(error)}
					<div class="fe-scatter-empty">Chart error: {error instanceof Error ? error.message : "Unknown"}</div>
				{/snippet}
			</svelte:boundary>
		</div>
	{:else}
		<div class="fe-error-wrap">
			<PanelErrorState
				title="No data"
				message="Research data could not be loaded."
			/>
		</div>
	{/if}
</div>

<style>
	.fe-root {
		display: flex;
		flex-direction: column;
		width: 100%;
		height: 100%;
		min-height: 0;
		overflow: auto;
		background: var(--ii-surface);
	}

	.fe-error-wrap {
		display: flex;
		align-items: center;
		justify-content: center;
		flex: 1;
		padding: 48px 24px;
	}

	/* --- Header --- */
	.fe-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 16px;
		padding: 16px 24px 12px;
		border-bottom: 1px solid var(--ii-border);
		flex-shrink: 0;
	}

	.fe-header-left {
		display: flex;
		align-items: baseline;
		gap: 12px;
		min-width: 0;
	}

	.fe-ticker {
		font-size: 1.25rem;
		font-weight: 700;
		color: var(--ii-text-primary);
		letter-spacing: 0.02em;
	}

	.fe-name {
		font-size: 0.875rem;
		color: var(--ii-text-secondary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.fe-as-of {
		font-size: 0.75rem;
		color: var(--ii-text-muted);
		white-space: nowrap;
	}

	/* --- 3-Panel Grid --- */
	.fe-grid {
		display: grid;
		grid-template-columns: 45% 40% 15%;
		gap: 1px;
		background: var(--ii-border);
		flex-shrink: 0;
	}

	.fe-panel {
		min-width: 0;
		min-height: 0;
		overflow: hidden;
		background: var(--ii-surface);
	}

	/* --- Stats Card --- */
	.fe-stats-card {
		display: flex;
		flex-direction: column;
		gap: 16px;
		padding: 18px 14px;
		height: 100%;
	}

	.fe-stats-card h2 {
		margin: 0;
		font-size: 1rem;
		color: var(--ii-text-secondary);
	}

	.fe-stats-grid {
		display: flex;
		flex-direction: column;
		gap: 12px;
	}

	.fe-stat {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.fe-stat-label {
		font-size: 0.6875rem;
		color: var(--ii-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}

	.fe-stat-value {
		font-size: 1.125rem;
		font-weight: 600;
		color: var(--ii-text-primary);
		font-variant-numeric: tabular-nums;
	}

	.fe-stat-value--date {
		font-size: 0.8125rem;
		font-weight: 500;
	}

	/* --- Significance Legend --- */
	.fe-legend {
		margin-top: auto;
		padding-top: 12px;
		border-top: 1px solid var(--ii-border);
	}

	.fe-legend h3 {
		margin: 0 0 8px;
		font-size: 0.6875rem;
		color: var(--ii-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}

	.fe-legend-items {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.fe-legend-dot {
		font-size: 0.75rem;
		color: var(--ii-text-secondary);
		display: flex;
		align-items: center;
		gap: 6px;
	}

	.fe-legend-dot::before {
		content: "";
		display: inline-block;
		width: 8px;
		height: 8px;
		border-radius: 50%;
	}

	.fe-legend-dot--high::before {
		background: #22c55e;
	}

	.fe-legend-dot--medium::before {
		background: #eab308;
	}

	.fe-legend-dot--low::before {
		background: #94a3b8;
	}

	.fe-legend-dot--none::before {
		background: #6b7280;
	}

	/* --- Full-width Scatter --- */
	.fe-scatter-wrap {
		flex-shrink: 0;
		border-top: 1px solid var(--ii-border);
	}

	.fe-scatter-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 200px;
		padding: 24px;
		color: var(--ii-text-muted);
		font-size: 0.875rem;
	}

	/* --- Responsive --- */
	@media (max-width: 1280px) {
		.fe-grid {
			grid-template-columns: 1fr 1fr;
			grid-template-rows: auto auto;
		}

		.fe-panel--stats {
			grid-column: 1 / -1;
		}
	}

	@media (max-width: 768px) {
		.fe-grid {
			grid-template-columns: 1fr;
		}

		.fe-panel--stats {
			grid-column: auto;
		}

		.fe-header {
			flex-direction: column;
			align-items: flex-start;
			gap: 4px;
		}
	}
</style>
