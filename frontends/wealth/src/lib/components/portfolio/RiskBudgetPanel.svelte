<!--
  RiskBudgetPanel — PR-A13 state owner for the Builder risk budget
  surface. Composes:
    1. RiskBudgetSlider (operator edits the tail loss limit)
    2. AchievableReturnBandChart (derived from latest cascade_telemetry)
    3. Signal banner (operator_signal → copy + tone)

  Two-channel state design is deliberate: ``previewBand`` is reserved for
  PR-A13.2 (live drag preview via POST /preview-cvar). A13 never writes to
  it, but the ``previewBand ?? serverBand`` precedence means A13.2 can
  wire in without rewriting the dependency graph.
-->
<script lang="ts">
	import { formatPercent } from "@investintell/ui";
	import { workspace } from "$lib/state/portfolio-workspace.svelte";
	import type { ModelPortfolio } from "$lib/types/model-portfolio";
	import type { PortfolioCalibration } from "$lib/types/portfolio-calibration";
	import type { AchievableReturnBand } from "$lib/types/cascade-telemetry";
	import { defaultCvarForProfile } from "$lib/util/profile-defaults";
	import RiskBudgetSlider from "./RiskBudgetSlider.svelte";
	import AchievableReturnBandChart from "./AchievableReturnBandChart.svelte";

	interface Props {
		portfolio: ModelPortfolio;
		calibration: PortfolioCalibration;
		snapshot?: Partial<PortfolioCalibration> | null;
		onChange: (patch: Partial<PortfolioCalibration>) => void;
	}

	let { portfolio, calibration, snapshot, onChange }: Props = $props();

	const profileDefault = $derived(defaultCvarForProfile(portfolio.profile));
	const cvarLimit = $derived(calibration.cvar_limit);

	const serverBand = $derived(
		workspace.constructionRun?.cascade_telemetry?.achievable_return_band ?? null,
	);
	const serverSignal = $derived(
		workspace.constructionRun?.cascade_telemetry?.operator_signal ?? null,
	);
	const minAchievableCvar = $derived(
		workspace.constructionRun?.cascade_telemetry?.min_achievable_cvar ?? null,
	);

	// PR-A13.2 slot — reserved for live preview. A13 never writes here.
	let previewBand = $state<AchievableReturnBand | null>(null);
	const band = $derived(previewBand ?? serverBand);

	const belowFloor = $derived(serverSignal?.kind === "cvar_limit_below_universe_floor");
	const dataMissing = $derived(serverSignal?.kind === "upstream_data_missing");
	const polytopeEmpty = $derived(serverSignal?.kind === "constraint_polytope_empty");
</script>

<div class="rbp-root">
	<RiskBudgetSlider
		value={cvarLimit}
		{profileDefault}
		profile={portfolio.profile}
		onChange={(v) => onChange({ cvar_limit: v })}
		originalValue={snapshot?.cvar_limit as number | undefined}
	/>

	{#if dataMissing}
		<div class="rbp-banner rbp-banner--empty" role="status">
			<p class="rbp-banner__msg">
				We don't have enough return history for this universe to model an achievable
				range. Add instruments with at least 36 months of NAV, or check the Universe
				column.
			</p>
		</div>
	{:else if polytopeEmpty}
		<div class="rbp-banner rbp-banner--blocking" role="alert">
			<p class="rbp-banner__msg">
				The current strategic allocation has no feasible portfolio. Adjust block
				min/max bounds.
			</p>
		</div>
	{:else}
		<AchievableReturnBandChart
			{band}
			{cvarLimit}
			{minAchievableCvar}
			height={220}
		/>
		<div class="rbp-stats" data-testid="rbp-stats">
			{#if band}
				<div class="rbp-stats__primary">
					At your tail loss limit: <strong>{formatPercent(band.upper, 2)}</strong> expected
				</div>
				<div class="rbp-stats__range">
					Achievable range across this universe:
					{formatPercent(band.lower, 2)} – {formatPercent(band.upper, 2)}
				</div>
			{:else}
				<div class="rbp-stats__empty">
					Run a construction to see the achievable return band.
				</div>
			{/if}
		</div>
		{#if belowFloor && minAchievableCvar !== null}
			<div class="rbp-banner rbp-banner--warning" role="status">
				<p class="rbp-banner__msg">
					Your tail loss limit ({formatPercent(cvarLimit, 2)}) sits below the lowest
					tail risk this universe can deliver ({formatPercent(minAchievableCvar, 2)}).
					We're showing the lowest-tail-risk portfolio achievable. Loosen the limit or
					expand the universe.
				</p>
			</div>
		{/if}
	{/if}
</div>

<style>
	.rbp-root {
		display: flex;
		flex-direction: column;
		gap: 12px;
	}
	.rbp-stats {
		display: flex;
		flex-direction: column;
		gap: 4px;
		font-family: var(--terminal-font-mono);
	}
	.rbp-stats__primary {
		font-size: 12px;
		color: var(--terminal-fg-primary);
	}
	.rbp-stats__range {
		font-size: 11px;
		color: var(--terminal-fg-muted);
	}
	.rbp-stats__empty {
		font-size: 11px;
		color: var(--terminal-fg-muted);
		font-style: italic;
	}
	.rbp-banner {
		padding: 10px 12px;
		border-left: 3px solid var(--terminal-fg-muted);
		background: var(--terminal-bg-panel);
		font-family: var(--terminal-font-mono);
	}
	.rbp-banner--warning {
		border-left-color: var(--terminal-status-warning);
	}
	.rbp-banner--blocking {
		border-left-color: var(--terminal-status-error);
	}
	.rbp-banner--empty {
		border-left-color: var(--terminal-fg-muted);
	}
	.rbp-banner__msg {
		margin: 0;
		font-size: 11px;
		line-height: 1.45;
		color: var(--terminal-fg-secondary);
	}
</style>
