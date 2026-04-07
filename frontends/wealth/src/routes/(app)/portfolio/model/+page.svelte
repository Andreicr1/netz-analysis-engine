<!--
  Model — Active portfolio analysis and monitoring.
  Top: portfolio allocation chart (full-width).
  Sub-pills: Holdings | Stress Testing | Overlap | Rebalance
  Below: full-width panel content with strategic block table, stress, overlap, rebalance.
-->
<script lang="ts">
	import { getContext, onDestroy } from "svelte";
	import { EmptyState, ConsequenceDialog, Toast, formatPercent } from "@investintell/ui";
	import { workspace } from "$lib/state/portfolio-workspace.svelte";
	import { portfolioDisplayName } from "$lib/constants/blocks";
	import MainPortfolioChart from "$lib/components/portfolio/MainPortfolioChart.svelte";
	import PortfolioOverview from "$lib/components/portfolio/PortfolioOverview.svelte";
	import StressTestPanel from "$lib/components/portfolio/StressTestPanel.svelte";
	import OverlapScannerPanel from "$lib/components/portfolio/OverlapScannerPanel.svelte";
	import RebalanceSimulationPanel from "$lib/components/portfolio/RebalanceSimulationPanel.svelte";
	import FactorAnalysisPanel from "$lib/components/portfolio/FactorAnalysisPanel.svelte";
	import ConstructionAdvisor from "$lib/components/model-portfolio/ConstructionAdvisor.svelte";
	import JobProgressTracker from "$lib/components/model-portfolio/JobProgressTracker.svelte";
	import ReportGeneratorCard from "$lib/components/model-portfolio/ReportGeneratorCard.svelte";
	import ReportVault from "$lib/components/model-portfolio/ReportVault.svelte";
	import { createPortfolioReportsStore, type PortfolioReportsStore } from "$lib/stores/portfolio-reports.svelte";
	import type { ModelPortfolio, ReportHistoryResponse } from "$lib/types/model-portfolio";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();
	let portfolios = $derived((data.portfolios ?? []) as ModelPortfolio[]);

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	workspace.setGetToken(getToken);

	// ── Reports Store (lifecycle-managed) ─────────────────────
	let reportsStore = $state<PortfolioReportsStore | null>(null);

	function initReportsStore(portfolioId: string) {
		// Destroy previous store if switching portfolios
		reportsStore?.destroy();

		const initialReports = (data.initialReports as Record<string, ReportHistoryResponse> | undefined)?.[portfolioId];
		reportsStore = createPortfolioReportsStore({
			portfolioId,
			getToken,
			initialReports: initialReports?.reports,
		});
	}

	// Re-init reports store when portfolio changes
	$effect(() => {
		if (workspace.portfolioId) {
			initReportsStore(workspace.portfolioId);
		} else {
			reportsStore?.destroy();
			reportsStore = null;
		}
	});

	onDestroy(() => {
		reportsStore?.destroy();
	});

	const subTabs = [
		{ value: "overview", label: "Holdings" },
		{ value: "factor", label: "Factor Analysis" },
		{ value: "stress", label: "Stress Testing" },
		{ value: "overlap", label: "Overlap" },
		{ value: "rebalance", label: "Rebalance" },
		{ value: "reporting", label: "Reporting" },
	] as const;

	let chartTitle = $derived(
		workspace.portfolio
			? portfolioDisplayName(workspace.portfolio.display_name)
			: "No portfolio selected"
	);

	// ── Construction Advisor auto-fetch on CVaR violation ─────────────
	// Auto-fetch advice once when CVaR is violated (guards against retry loop on 4xx)
	$effect(() => {
		if (workspace.cvarViolated && workspace.portfolioId && !workspace.adviceFetched && !workspace.isLoadingAdvice) {
			workspace.fetchConstructionAdvice();
		}
	});

	// ── Activation flow ──────────────────────────────────────────────────
	let showActivateDialog = $state(false);
	let toastMessage = $state<string | null>(null);
	let toastType = $state<"success" | "error">("success");

	let canActivate = $derived(
		workspace.portfolio?.status === "draft"
		&& !workspace.cvarViolated
		&& workspace.funds.length > 0
	);

	let isDraft = $derived(workspace.portfolio?.status === "draft");

	async function handleActivate() {
		try {
			await workspace.activatePortfolio();
			showActivateDialog = false;
			toastType = "success";
			toastMessage = "Portfolio activated — now available for rebalancing and monitoring.";
		} catch {
			toastType = "error";
			toastMessage = workspace.lastError?.message ?? "Activation failed";
		}
	}

	function handleAdvisorReconstruct() {
		workspace.constructPortfolio();
	}
</script>

<svelte:head>
	<title>Model — InvestIntell</title>
</svelte:head>

<div class="mdl-page">

	<!-- Portfolio selector (horizontal pills) -->
	<div class="mdl-portfolio-bar">
		{#each portfolios as mp (mp.id)}
			{@const active = mp.id === workspace.portfolioId}
			<button
				type="button"
				class="mdl-portfolio-pill"
				class:mdl-portfolio-pill--active={active}
				onclick={() => workspace.selectPortfolio(mp)}
			>
				{portfolioDisplayName(mp.display_name)}
			</button>
		{/each}
	</div>

	{#if !workspace.portfolio}
		<div class="mdl-empty">
			<EmptyState
				title="No portfolio selected"
				message="Select a model portfolio above to view its detail."
			/>
		</div>
	{:else}
		<!-- Chart card (full-width, spacious) -->
		<div class="mdl-chart-card">
			<div class="mdl-chart-header">
				<span class="mdl-chart-title">{chartTitle}</span>
			</div>
			<div class="mdl-chart-body">
				<MainPortfolioChart />
			</div>
		</div>

		<!-- Action bar: sub-pills + activate -->
		<div class="mdl-action-bar">
			<div class="mdl-sub-pills">
				{#each subTabs as tab (tab.value)}
					{@const active = workspace.activeModelTab === tab.value}
					<button
						type="button"
						class="mdl-sub-pill"
						class:mdl-sub-pill--active={active}
						onclick={() => workspace.activeModelTab = tab.value}
					>
						{tab.label}
					</button>
				{/each}
			</div>

			{#if isDraft}
				<div class="mdl-activate-zone">
					{#if workspace.cvarViolated}
						<span class="mdl-activate-hint" title="CVaR limit exceeded — resolve via Construction Advisor before activating">
							CVaR limit exceeded
						</span>
					{/if}
					<button
						type="button"
						class="mdl-activate-btn"
						class:mdl-activate-btn--disabled={!canActivate}
						disabled={!canActivate}
						title={!canActivate
							? workspace.cvarViolated
								? "CVaR limit exceeded — add diversifying funds or adjust profile before activation"
								: "Portfolio must have funds and pass risk limits to activate"
							: "Activate portfolio for rebalancing and monitoring"}
						onclick={() => (showActivateDialog = true)}
					>
						{workspace.isActivating ? "Activating…" : "Activate Portfolio"}
					</button>
				</div>
			{/if}
		</div>

		<!-- Construction Advisor — auto-shown when CVaR is violated -->
		{#if workspace.cvarViolated && workspace.activeModelTab === "overview"}
			<div class="mdl-advisor">
				<ConstructionAdvisor
					portfolioId={workspace.portfolioId ?? ""}
					externalAdvice={workspace.advice}
					externalLoading={workspace.isLoadingAdvice}
					externalError={workspace.lastError?.action === "construction-advice" ? workspace.lastError.message : undefined}
					onReconstruct={handleAdvisorReconstruct}
				/>
			</div>
		{/if}

		<!-- Panel content -->
		<div class="mdl-content">
			{#if workspace.activeModelTab === "overview"}
				<PortfolioOverview />
			{:else if workspace.activeModelTab === "factor"}
				<FactorAnalysisPanel />
			{:else if workspace.activeModelTab === "stress"}
				<StressTestPanel />
			{:else if workspace.activeModelTab === "overlap"}
				<OverlapScannerPanel />
			{:else if workspace.activeModelTab === "reporting"}
				{#if reportsStore}
					{#if reportsStore.hasActiveJobs}
						<JobProgressTracker jobs={reportsStore.activeJobs} />
					{/if}

					<ReportGeneratorCard
						canGenerate={!!workspace.portfolio?.fund_selection_schema}
						generating={reportsStore.hasActiveJobs}
						onGenerate={(req) => reportsStore?.triggerGeneration(req)}
					/>

					<ReportVault
						portfolioId={workspace.portfolioId ?? ""}
						reports={reportsStore.reports}
						loading={reportsStore.reportsLoading}
						error={reportsStore.reportsError}
						onRefresh={() => reportsStore?.refreshReports()}
					/>
				{/if}
			{:else}
				<RebalanceSimulationPanel />
			{/if}
		</div>
	{/if}
</div>

<!-- Activation confirmation dialog -->
<ConsequenceDialog
	bind:open={showActivateDialog}
	title="Activate Portfolio"
	impactSummary="This portfolio will become available for live rebalancing and risk monitoring. This action transitions the status from draft to active."
	requireRationale={true}
	rationaleLabel="Activation rationale"
	rationalePlaceholder="Brief justification for activating this portfolio (e.g., IC approval date, mandate reference)…"
	rationaleMinLength={10}
	confirmLabel={workspace.isActivating ? "Activating…" : "Confirm Activation"}
	metadata={[
		{ label: "Portfolio", value: workspace.portfolio?.display_name ?? "", emphasis: true },
		{ label: "Profile", value: workspace.portfolio?.profile ?? "" },
		{ label: "Funds", value: String(workspace.funds.length) },
		...(workspace.optimizationMeta?.cvar_95 != null
			? [{ label: "CVaR 95%", value: formatPercent(workspace.optimizationMeta.cvar_95) }]
			: []),
		...(workspace.optimizationMeta?.cvar_limit != null
			? [{ label: "CVaR Limit", value: formatPercent(workspace.optimizationMeta.cvar_limit) }]
			: []),
	]}
	onConfirm={handleActivate}
	onCancel={() => (showActivateDialog = false)}
/>

<!-- Toast feedback -->
{#if toastMessage}
	<Toast
		message={toastMessage}
		type={toastType}
		duration={5000}
		onDismiss={() => (toastMessage = null)}
	/>
{/if}

<!-- Error notification -->
{#if workspace.lastError}
	<div class="mdl-error-toast">
		<span>
			<strong>{workspace.lastError.action} failed:</strong>
			{workspace.lastError.message}
		</span>
		<button class="mdl-error-close" onclick={() => { workspace.lastError = null; }}>&times;</button>
	</div>
{/if}

<style>
	.mdl-page {
		height: 100%;
		display: flex;
		flex-direction: column;
		gap: 20px;
		overflow: hidden;
	}

	.mdl-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		flex: 1;
	}

	/* ── Portfolio selector ── */
	.mdl-portfolio-bar {
		display: flex;
		align-items: center;
		gap: 6px;
		flex-shrink: 0;
	}

	.mdl-portfolio-pill {
		display: inline-flex;
		align-items: center;
		padding: 7px 18px;
		border: 1px solid #3a3b44;
		border-radius: 36px;
		background: transparent;
		color: #a1a1aa;
		font-size: 13px;
		font-weight: 600;
		font-family: "Urbanist", sans-serif;
		cursor: pointer;
		white-space: nowrap;
		transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
	}

	.mdl-portfolio-pill:hover {
		background: #22232a;
		border-color: #52525b;
		color: #fff;
	}

	.mdl-portfolio-pill--active {
		background: #0177fb;
		border-color: transparent;
		color: #fff;
	}

	.mdl-portfolio-pill--active:hover {
		background: #0166d9;
	}

	/* ── Chart card ── */
	.mdl-chart-card {
		flex-shrink: 0;
		height: 420px;
		background: #141519;
		border-radius: 20px;
		border: 1px solid rgba(64, 66, 73, 0.3);
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}

	.mdl-chart-header {
		display: flex;
		align-items: center;
		padding: 12px 20px;
		flex-shrink: 0;
	}

	.mdl-chart-title {
		font-size: 15px;
		font-weight: 600;
		color: #cbccd1;
		font-family: "Urbanist", sans-serif;
	}

	.mdl-chart-body {
		flex: 1;
		min-height: 0;
		padding: 0 12px 12px;
	}

	/* ── Action bar (pills + activate) ── */
	.mdl-action-bar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		flex-shrink: 0;
	}

	/* ── Sub-pills ── */
	.mdl-sub-pills {
		display: flex;
		align-items: center;
		gap: 6px;
		flex-shrink: 0;
	}

	.mdl-sub-pill {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		padding: 8px 20px;
		border: 1px solid #3a3b44;
		border-radius: 36px;
		background: transparent;
		color: #a1a1aa;
		font-size: 14px;
		font-weight: 600;
		font-family: "Urbanist", sans-serif;
		cursor: pointer;
		white-space: nowrap;
		transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
		letter-spacing: 0.02em;
	}

	.mdl-sub-pill:hover {
		background: #22232a;
		border-color: #52525b;
		color: #fff;
	}

	.mdl-sub-pill--active {
		background: #0177fb;
		border-color: transparent;
		color: #fff;
	}

	.mdl-sub-pill--active:hover {
		background: #0166d9;
	}

	/* ── Activate zone ── */
	.mdl-activate-zone {
		display: flex;
		align-items: center;
		gap: 10px;
		flex-shrink: 0;
	}

	.mdl-activate-hint {
		font-size: 12px;
		font-weight: 600;
		color: #f87171;
		white-space: nowrap;
	}

	.mdl-activate-btn {
		display: inline-flex;
		align-items: center;
		padding: 8px 22px;
		border: 1px solid transparent;
		border-radius: 36px;
		background: #11ec79;
		color: #0a0b0e;
		font-size: 13px;
		font-weight: 700;
		font-family: "Urbanist", sans-serif;
		cursor: pointer;
		white-space: nowrap;
		transition: background 120ms ease, opacity 120ms ease;
	}

	.mdl-activate-btn:hover:not(:disabled) {
		background: #0fd96d;
	}

	.mdl-activate-btn--disabled,
	.mdl-activate-btn:disabled {
		background: #3a3b44;
		color: #71717a;
		cursor: not-allowed;
		opacity: 0.7;
	}

	/* ── Advisor section ── */
	.mdl-advisor {
		flex-shrink: 0;
	}

	/* ── Content ── */
	.mdl-content {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
	}

	/* ── Error toast ── */
	.mdl-error-toast {
		position: fixed;
		bottom: 24px;
		right: 24px;
		z-index: 50;
		display: flex;
		max-width: 384px;
		align-items: flex-start;
		gap: 12px;
		border-radius: 16px;
		border: 1px solid rgba(239, 68, 68, 0.3);
		background: rgba(69, 10, 10, 0.9);
		padding: 12px 16px;
		font-size: 14px;
		color: #fecaca;
		box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
		backdrop-filter: blur(8px);
	}

	.mdl-error-close {
		flex-shrink: 0;
		color: #f87171;
		background: none;
		border: none;
		cursor: pointer;
		font-size: 18px;
	}
	.mdl-error-close:hover { color: #fecaca; }
</style>
