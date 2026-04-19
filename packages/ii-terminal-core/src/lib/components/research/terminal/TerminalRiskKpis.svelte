<!--
  TerminalRiskKpis — right panel showing real risk metrics for selected node.
  Fetches from GET /instruments/{instrumentId}/risk-metrics.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { formatNumber, formatPercent } from "@investintell/ui";
	import type { TreeNode } from "./TerminalAssetTree.svelte";
	import ScoreBreakdownPopover from "./ScoreBreakdownPopover.svelte";
	import { createClientApiClient } from "../../../api/client";

	interface RiskMetrics {
		instrument_id: string;
		score_components: Record<string, number> | null;
		manager_score: number | null;
		sharpe_1y: number | null;
		volatility_1y: number | null;
		max_drawdown_1y: number | null;
		cvar_95_1m: number | null;
		return_1y: number | null;
		return_3y_ann: number | null;
		sortino_1y: number | null;
		max_drawdown_3y: number | null;
		alpha_1y: number | null;
		beta_1y: number | null;
		information_ratio_1y: number | null;
		tracking_error_1y: number | null;
		blended_momentum_score: number | null;
		volatility_garch: number | null;
	}

	interface Props {
		selectedNode: TreeNode | null;
	}

	let { selectedNode }: Props = $props();
	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

	let risk = $state<RiskMetrics | null>(null);
	let loading = $state(false);
	let errorMessage = $state<string | null>(null);

	// Fetch real risk metrics when selected node changes
	$effect(() => {
		const iid = selectedNode?.instrumentId;
		if (!iid) {
			risk = null;
			errorMessage = null;
			loading = false;
			return;
		}

		let cancelled = false;
		loading = true;
		errorMessage = null;

		(async () => {
			try {
				const data = await api.get<RiskMetrics>(`/instruments/${iid}/risk-metrics`);
				if (!cancelled) {
					risk = data;
					errorMessage = null;
				}
			} catch (err: unknown) {
				if (!cancelled) {
					risk = null;
					if (err instanceof Error && err.message.includes("404")) {
						errorMessage = null; // 404 = no data, not an error
					} else {
						errorMessage = err instanceof Error ? err.message : "Failed to fetch risk metrics";
					}
				}
			} finally {
				if (!cancelled) loading = false;
			}
		})();

		return () => { cancelled = true; };
	});

	function pctClass(v: number | null): string {
		if (v == null) return "";
		if (v > 0) return "pos";
		if (v < 0) return "neg";
		return "";
	}

	let showPopover = $state(false);
	let scoreButtonRef = $state<HTMLElement>(undefined!);
	let popoverTop = $state(0);
	let popoverLeft = $state(0);

	function togglePopover(e: MouseEvent) {
		if (!showPopover) {
			const rect = scoreButtonRef.getBoundingClientRect();
			popoverTop = rect.bottom + 8;
			popoverLeft = rect.right - 280;
			showPopover = true;
		} else {
			showPopover = false;
		}
	}

	function closePopover() {
		if (showPopover) showPopover = false;
	}

	$effect(() => {
		if (showPopover) {
			window.addEventListener("click", closePopover);
			return () => window.removeEventListener("click", closePopover);
		}
	});

	function stopPropagation(e: MouseEvent) {
		e.stopPropagation();
	}

	// Hide popover if node changes
	$effect(() => {
		if (selectedNode) {
			showPopover = false;
		}
	});

	// Tear Sheet Export Logic
	let isGeneratingPdf = $state(false);

	async function exportTearSheet() {
		if (!selectedNode || isGeneratingPdf) return;

		const externalId = selectedNode.ticker ?? selectedNode.id;
		isGeneratingPdf = true;

		try {
			const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
			const token = await getToken();
			const response = await fetch(`${API_BASE}/wealth/funds/${externalId}/reports/tear-sheet`, {
				method: "POST",
				headers: {
					"Authorization": `Bearer ${token}`
				}
			});

			if (!response.ok) {
				throw new Error("Failed to generate Tear Sheet");
			}

			const blob = await response.blob();
			const url = URL.createObjectURL(blob);

			const a = document.createElement("a");
			a.style.display = "none";
			a.href = url;
			a.download = `${externalId}-tear-sheet.pdf`;

			document.body.appendChild(a);
			a.click();

			setTimeout(() => {
				document.body.removeChild(a);
				URL.revokeObjectURL(url);
			}, 100);
		} catch (error) {
			console.error("Export failed:", error);
		} finally {
			isGeneratingPdf = false;
		}
	}

	const hasData = $derived(risk != null);
	const noData = $derived(!loading && !risk && !errorMessage && selectedNode?.instrumentId != null);
</script>

<div class="rk-root">
	{#if loading}
		<div class="rk-empty">
			<span class="rk-empty-text">Loading risk metrics...</span>
		</div>
	{:else if errorMessage}
		<div class="rk-empty">
			<span class="rk-empty-text rk-err">{errorMessage}</span>
		</div>
	{:else if noData || (!selectedNode?.instrumentId && selectedNode)}
		<div class="rk-empty">
			<span class="rk-empty-icon">&#9670;</span>
			<span class="rk-empty-text">No risk data available</span>
		</div>
	{:else if hasData && selectedNode}
		<div class="rk-header">
			<div class="rk-header-left">
				<span class="rk-node-label">
					{selectedNode.ticker ?? selectedNode.label}
				</span>
				<span class="rk-node-type">{selectedNode.fundType}</span>
			</div>
			<div class="rk-header-right">
				<div
					class="rk-score-btn"
					bind:this={scoreButtonRef}
					onclick={(e) => { stopPropagation(e); togglePopover(e); }}
					onkeydown={(e) => { if (e.key === "Enter") togglePopover(e as any); }}
					role="button"
					tabindex="0"
					aria-haspopup="dialog"
					aria-expanded={showPopover}
				>
					<div class="rk-score-label">SCORE</div>
					<div class="rk-score-val">
						{#if risk!.manager_score == null}
							<span class="rk-na">--</span>
						{:else if risk!.manager_score >= 75}
							<span class="elite">[ ELITE ]</span>
						{:else if risk!.manager_score < 40}
							<span class="eviction">[ EVICTION ]</span>
						{:else}
							{formatNumber(risk!.manager_score, 0)}
						{/if}
					</div>
				</div>

				<button
					class="rk-export-btn {isGeneratingPdf ? 'exporting' : ''}"
					onclick={exportTearSheet}
					disabled={isGeneratingPdf}
				>
					{isGeneratingPdf ? "[ GENERATING PDF... ]" : "[ EXPORT TEAR SHEET ]"}
				</button>
			</div>
		</div>

		<!-- Return & Risk -->
		<div class="rk-section">
			<div class="rk-section-title">RETURN & RISK</div>
			<div class="rk-block">
				<div class="rk-kpi">
					<span class="rk-label">Annual Return</span>
					<span class="rk-value {pctClass(risk!.return_1y)}">
						{risk!.return_1y != null ? formatPercent(risk!.return_1y) : "--"}
					</span>
				</div>
				<div class="rk-kpi">
					<span class="rk-label">Annual Volatility</span>
					<span class="rk-value">
						{risk!.volatility_1y != null ? formatPercent(risk!.volatility_1y) : "--"}
					</span>
				</div>
				<div class="rk-kpi">
					<span class="rk-label">Sharpe Ratio</span>
					<span class="rk-value">
						{risk!.sharpe_1y != null ? formatNumber(risk!.sharpe_1y, 2) : "--"}
					</span>
				</div>
				<div class="rk-kpi">
					<span class="rk-label">Sortino Ratio</span>
					<span class="rk-value">
						{risk!.sortino_1y != null ? formatNumber(risk!.sortino_1y, 2) : "--"}
					</span>
				</div>
			</div>
		</div>

		<!-- Drawdown Analysis -->
		<div class="rk-section">
			<div class="rk-section-title">DRAWDOWN ANALYSIS</div>
			<div class="rk-block">
				<div class="rk-kpi">
					<span class="rk-label">Max Drawdown (1Y)</span>
					<span class="rk-value neg">
						{risk!.max_drawdown_1y != null ? formatPercent(risk!.max_drawdown_1y) : "--"}
					</span>
				</div>
				<div class="rk-kpi">
					<span class="rk-label">Max Drawdown (3Y)</span>
					<span class="rk-value neg">
						{risk!.max_drawdown_3y != null ? formatPercent(risk!.max_drawdown_3y) : "--"}
					</span>
				</div>
				<div class="rk-kpi">
					<span class="rk-label">Risk Budget (1M)</span>
					<span class="rk-value neg">
						{risk!.cvar_95_1m != null ? formatPercent(risk!.cvar_95_1m) : "--"}
					</span>
				</div>
			</div>
		</div>

		<!-- Factor Exposure -->
		<div class="rk-section">
			<div class="rk-section-title">FACTOR EXPOSURE</div>
			<div class="rk-block">
				<div class="rk-kpi">
					<span class="rk-label">Beta</span>
					<span class="rk-value">
						{risk!.beta_1y != null ? formatNumber(risk!.beta_1y, 2) : "--"}
					</span>
				</div>
				<div class="rk-kpi">
					<span class="rk-label">Tracking Error</span>
					<span class="rk-value">
						{risk!.tracking_error_1y != null ? formatPercent(risk!.tracking_error_1y) : "--"}
					</span>
				</div>
				<div class="rk-kpi">
					<span class="rk-label">Information Ratio</span>
					<span class="rk-value {pctClass(risk!.information_ratio_1y)}">
						{risk!.information_ratio_1y != null ? formatNumber(risk!.information_ratio_1y, 2) : "--"}
					</span>
				</div>
				<div class="rk-kpi">
					<span class="rk-label">Alpha</span>
					<span class="rk-value {pctClass(risk!.alpha_1y)}">
						{risk!.alpha_1y != null ? formatPercent(risk!.alpha_1y) : "--"}
					</span>
				</div>
			</div>
		</div>

		<!-- Momentum -->
		<div class="rk-section">
			<div class="rk-section-title">MOMENTUM</div>
			<div class="rk-block">
				<div class="rk-kpi">
					<span class="rk-label">Momentum</span>
					<span class="rk-value">
						{risk!.blended_momentum_score != null ? formatNumber(risk!.blended_momentum_score, 0) + "/100" : "--"}
					</span>
				</div>
				<div class="rk-kpi">
					<span class="rk-label">Score</span>
					<span class="rk-value">
						{risk!.manager_score != null ? formatNumber(risk!.manager_score, 0) + "/100" : "--"}
					</span>
				</div>
			</div>
		</div>
	{:else}
		<div class="rk-empty">
			<span class="rk-empty-icon">&#9670;</span>
			<span class="rk-empty-text">Select a node to view risk analysis</span>
		</div>
	{/if}
</div>

{#if showPopover && risk}
	<div
		class="rk-popover-portal"
		style="top: {popoverTop}px; left: {popoverLeft}px;"
		onclick={stopPropagation}
		onkeydown={(e) => e.stopPropagation()}
		role="presentation"
	>
		<ScoreBreakdownPopover
			scoreComponents={risk.score_components}
			managerScore={risk.manager_score}
		/>
	</div>
{/if}

<style>
	.rk-root {
		display: flex;
		flex-direction: column;
		height: 100%;
		background: var(--terminal-bg-panel);
		border-left: var(--terminal-border-hairline);
		font-family: var(--terminal-font-mono);
		overflow-y: auto;
		overflow-x: hidden;
	}

	/* -- Header ----------------------------------------- */
	.rk-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 12px 14px 8px;
		border-bottom: var(--terminal-border-hairline);
		flex-shrink: 0;
	}

	.rk-header-left {
		display: flex;
		align-items: baseline;
		gap: 8px;
	}

	.rk-header-right {
		display: flex;
		align-items: center;
		gap: 12px;
	}

	.rk-node-label {
		font-size: var(--terminal-text-14);
		font-weight: 800;
		color: var(--terminal-fg-primary);
		letter-spacing: 0.04em;
	}

	.rk-node-type {
		font-size: 9px;
		font-weight: 600;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--terminal-fg-tertiary);
	}

	.rk-score-btn {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 4px 8px;
		border-radius: var(--terminal-radius-none);
		cursor: pointer;
		transition: background 150ms ease;
		user-select: none;
		background: transparent;
	}

	.rk-score-btn:hover {
		background: var(--terminal-bg-panel-raised);
	}

	.rk-score-label {
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.05em;
		color: var(--terminal-fg-tertiary);
	}

	.rk-score-val {
		font-size: var(--terminal-text-14);
		font-weight: 800;
		color: var(--terminal-fg-primary);
		font-variant-numeric: tabular-nums;
	}

	.rk-na { color: var(--terminal-fg-muted); }
	.elite { color: var(--terminal-accent-cyan); font-size: var(--terminal-text-11); letter-spacing: 0.05em; }
	.eviction { color: var(--terminal-accent-amber); font-size: var(--terminal-text-11); letter-spacing: 0.05em; }

	.rk-export-btn {
		background: transparent;
		border: var(--terminal-border-hairline);
		color: var(--terminal-fg-secondary);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: 0.05em;
		padding: 4px 8px;
		cursor: pointer;
		transition: all 150ms ease;
		outline: none;
	}

	.rk-export-btn:hover:not(:disabled) {
		border-color: var(--terminal-accent-cyan);
		color: var(--terminal-accent-cyan);
	}

	.rk-export-btn:disabled {
		cursor: not-allowed;
	}

	.rk-export-btn.exporting {
		color: var(--terminal-accent-amber);
		border-color: var(--terminal-accent-amber);
		animation: pulseBorder 1.5s infinite alternate;
	}

	@keyframes pulseBorder {
		0% { border-color: var(--terminal-accent-amber-dim); color: var(--terminal-accent-amber-dim); }
		100% { border-color: var(--terminal-accent-amber); color: var(--terminal-accent-amber); }
	}

	/* -- Section ---------------------------------------- */
	.rk-section {
		padding: 0 10px;
		margin-bottom: 2px;
	}

	.rk-section-title {
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.1em;
		color: var(--terminal-fg-muted);
		text-transform: uppercase;
		padding: 10px 4px 4px;
	}

	.rk-block {
		background: var(--terminal-bg-panel-raised);
		border-radius: var(--terminal-radius-none);
		padding: 8px 10px;
		display: flex;
		flex-direction: column;
		gap: 6px;
	}

	/* -- KPI row ---------------------------------------- */
	.rk-kpi {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 8px;
	}

	.rk-label {
		font-size: 9px;
		font-weight: 600;
		letter-spacing: 0.04em;
		color: var(--terminal-fg-tertiary);
		text-transform: uppercase;
		flex-shrink: 0;
	}

	.rk-value {
		font-size: var(--terminal-text-16);
		font-weight: 800;
		color: var(--terminal-fg-primary);
		font-variant-numeric: tabular-nums;
		text-align: right;
	}

	.pos { color: var(--terminal-status-success); }
	.neg { color: var(--terminal-status-error); }

	/* -- Empty ------------------------------------------ */
	.rk-empty {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 8px;
		height: 100%;
		color: var(--terminal-fg-muted);
	}

	.rk-empty-icon {
		font-size: 20px;
		opacity: 0.3;
	}

	.rk-empty-text {
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
		letter-spacing: 0.04em;
	}

	.rk-err {
		color: var(--terminal-status-error);
	}

	/* -- Popover Portal --------------------------------- */
	.rk-popover-portal {
		position: fixed;
		z-index: var(--terminal-z-dropdown);
	}
</style>
