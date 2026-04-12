<!--
  ScoreCompositionPanel — horizontal bar breakdown of composite score.
  Shows the 6 scoring components with weighted contributions.
  Fetches score_components from the fact-sheet detail endpoint.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { formatNumber } from "@investintell/ui";
	import { createClientApiClient } from "$lib/api/client";

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

	interface Props {
		id: string;
	}

	let { id }: Props = $props();

	interface ScoreComponent {
		name: string;
		key: string;
		weight: number;
		value: number;
		weighted: number;
	}

	const EQUITY_WEIGHTS: Record<string, { label: string; weight: number }> = {
		risk_adjusted_return: { label: "Risk-Adj Return", weight: 0.30 },
		return_consistency: { label: "Return Consistency", weight: 0.20 },
		drawdown_control: { label: "Drawdown Control", weight: 0.20 },
		information_ratio: { label: "Information Ratio", weight: 0.15 },
		fee_efficiency: { label: "Fee Efficiency", weight: 0.10 },
		flows_momentum: { label: "Flows Momentum", weight: 0.05 },
	};

	const FI_WEIGHTS: Record<string, { label: string; weight: number }> = {
		duration_management: { label: "Duration Mgmt", weight: 0.25 },
		duration_adjusted_drawdown: { label: "Dur-Adj Drawdown", weight: 0.25 },
		yield_consistency: { label: "Yield Consistency", weight: 0.20 },
		spread_capture: { label: "Spread Capture", weight: 0.20 },
		fee_efficiency: { label: "Fee Efficiency", weight: 0.10 },
	};

	let compositeScore = $state<number | null>(null);
	let components = $state<ScoreComponent[]>([]);
	let scoringModel = $state<string>("equity");
	let loading = $state(true);
	let hasData = $state(false);

	$effect(() => {
		if (!id) return;
		loading = true;
		hasData = false;

		api.get<any>(`/screener/catalog/detail/${id}`)
			.then((detail) => {
				const sm = detail?.scoring_metrics;
				if (sm?.manager_score != null) {
					compositeScore = sm.manager_score;
				}
				scoringModel = sm?.scoring_model || "equity";
				const weightMap = scoringModel === "fixed_income" ? FI_WEIGHTS : EQUITY_WEIGHTS;
				const sc = sm?.score_components;
				if (sc && typeof sc === "object") {
					const parsed: ScoreComponent[] = [];
					for (const [key, meta] of Object.entries(weightMap)) {
						const value = sc[key];
						if (value != null) {
							parsed.push({
								name: meta.label,
								key,
								weight: meta.weight,
								value: Number(value),
								weighted: Number(value) * meta.weight,
							});
						}
					}
					// Sort by weight descending (most important first)
					parsed.sort((a, b) => b.weight - a.weight);
					components = parsed;
					hasData = parsed.length > 0;
				}
				loading = false;
			})
			.catch(() => {
				loading = false;
			});
	});

	function scoreColor(v: number): string {
		if (v >= 70) return "var(--terminal-status-success, #22c55e)";
		if (v >= 40) return "var(--terminal-accent-amber, #f59e0b)";
		return "var(--terminal-status-error, #ef4444)";
	}
</script>

<section class="scp-root">
	<div class="scp-header">
		<span class="scp-title">SCORE COMPOSITION</span>
		{#if compositeScore != null}
			<span class="scp-composite" style="color: {scoreColor(compositeScore)}">
				{formatNumber(compositeScore, 1)}
			</span>
		{/if}
	</div>

	{#if loading}
		<div class="scp-loading">LOADING...</div>
	{:else if hasData}
		<div class="scp-bars">
			{#each components as comp (comp.key)}
				<div class="scp-bar-row">
					<span class="scp-bar-label">{comp.name}</span>
					<div class="scp-bar-track">
						<div
							class="scp-bar-fill"
							style="width: {Math.min(comp.value, 100)}%; background: {scoreColor(comp.value)};"
						></div>
					</div>
					<span class="scp-bar-value">{formatNumber(comp.value, 0)}</span>
					<span class="scp-bar-weighted">({formatNumber(comp.weighted, 1)})</span>
				</div>
			{/each}
		</div>
		{@const weightedSum = components.reduce((s, c) => s + c.weighted, 0)}
		<div class="scp-sum">
			<span>SUM</span>
			<span class="scp-sum-value">{formatNumber(weightedSum, 1)}</span>
		</div>
	{:else}
		<div class="scp-degraded">
			{#if compositeScore != null}
				<div class="scp-degraded-score">COMPOSITE: {formatNumber(compositeScore, 1)}</div>
			{/if}
			<div class="scp-degraded-weights">
				<div class="scp-degraded-title">Component weights ({scoringModel === "fixed_income" ? "FI" : "equity"} model):</div>
				{#each Object.entries(scoringModel === "fixed_income" ? FI_WEIGHTS : EQUITY_WEIGHTS) as [, meta]}
					<div class="scp-degraded-row">
						<span>{meta.label}</span>
						<span>{Math.round(meta.weight * 100)}%</span>
					</div>
				{/each}
			</div>
			<div class="scp-degraded-note">
				Individual component scores not available.
			</div>
		</div>
	{/if}
</section>

<style>
	.scp-root {
		background-color: #000;
		padding: 16px;
		display: flex;
		flex-direction: column;
		font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
		font-size: 0.75rem;
	}

	.scp-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 12px;
		border-bottom: 1px solid #222;
		padding-bottom: 4px;
	}

	.scp-title {
		font-size: 0.7rem;
		font-weight: 700;
		color: #9ca3af;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.scp-composite {
		font-size: 1rem;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
	}

	.scp-loading {
		text-align: center;
		color: #6b7280;
		padding: 12px;
		text-transform: uppercase;
		letter-spacing: 0.1em;
	}

	.scp-bars {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}

	.scp-bar-row {
		display: grid;
		grid-template-columns: 110px 1fr 28px 40px;
		align-items: center;
		gap: 8px;
	}

	.scp-bar-label {
		font-size: 0.65rem;
		color: #9ca3af;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.scp-bar-track {
		height: 8px;
		background: #1a1a2e;
		border: 1px solid rgba(255, 255, 255, 0.04);
		position: relative;
	}

	.scp-bar-fill {
		height: 100%;
		transition: width 400ms ease;
	}

	.scp-bar-value {
		text-align: right;
		font-weight: 600;
		color: #d1d5db;
		font-variant-numeric: tabular-nums;
	}

	.scp-bar-weighted {
		text-align: right;
		color: #6b7280;
		font-variant-numeric: tabular-nums;
		font-size: 0.65rem;
	}

	.scp-sum {
		display: flex;
		justify-content: flex-end;
		gap: 12px;
		margin-top: 8px;
		padding-top: 6px;
		border-top: 1px solid #222;
		color: #6b7280;
		font-size: 0.65rem;
	}

	.scp-sum-value {
		font-weight: 700;
		color: #d1d5db;
		font-variant-numeric: tabular-nums;
	}

	/* Degraded view when component scores are not available */
	.scp-degraded {
		color: #6b7280;
	}

	.scp-degraded-score {
		font-size: 0.875rem;
		font-weight: 700;
		color: #d1d5db;
		margin-bottom: 12px;
	}

	.scp-degraded-title {
		font-size: 0.65rem;
		color: #9ca3af;
		margin-bottom: 6px;
	}

	.scp-degraded-row {
		display: flex;
		justify-content: space-between;
		padding: 2px 0;
		font-size: 0.7rem;
	}

	.scp-degraded-note {
		margin-top: 12px;
		font-size: 0.65rem;
		font-style: italic;
		color: #4b5563;
	}
</style>
