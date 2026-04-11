<!--
  TerminalRiskKpis — right panel showing risk statistics for selected node.
  High-contrast blocks with small labels (9px) and large numbers (16px tabular-nums).
-->
<script lang="ts">
	import { getContext, onDestroy } from "svelte";
	import { formatNumber } from "@investintell/ui";
	import type { TreeNode } from "./TerminalAssetTree.svelte";
	import ScoreBreakdownPopover from "./ScoreBreakdownPopover.svelte";

	interface RiskData {
		annReturn: number;
		annVolatility: number;
		sharpe: number;
		sortino: number;
		maxDrawdown: number;
		currentDrawdown: number;
		longestDrawdownDays: number;
		upCapture: number;
		downCapture: number;
		beta: number;
		trackingError: number;
		infoRatio: number;
		managerScore: number;
	}

	interface Props {
		selectedNode: TreeNode | null;
	}

	let { selectedNode }: Props = $props();
	const getToken = getContext<() => Promise<string>>("netz:getToken");

	// Generate deterministic mock risk data from node id
	function mockRisk(node: TreeNode): RiskData {
		let hash = 0;
		for (let i = 0; i < node.id.length; i++) {
			hash = (hash * 31 + node.id.charCodeAt(i)) | 0;
		}
		const seed = Math.abs(hash);
		const r = (min: number, max: number) => min + ((seed * 7 + min * 13) % 1000) / 1000 * (max - min);

		return {
			annReturn: r(2, 28),
			annVolatility: r(5, 22),
			sharpe: r(0.2, 2.1),
			sortino: r(0.3, 2.8),
			maxDrawdown: -r(4, 35),
			currentDrawdown: -r(0, 8),
			longestDrawdownDays: Math.floor(r(30, 420)),
			upCapture: r(80, 120),
			downCapture: r(60, 110),
			beta: r(0.4, 1.3),
			trackingError: r(1, 8),
			infoRatio: r(-0.2, 1.5),
			managerScore: r(20, 95),
		};
	}

	const risk = $derived(selectedNode ? mockRisk(selectedNode) : null);

	function fmt(v: number, d: number = 2): string {
		return formatNumber(v, d);
	}

	function pctClass(v: number): string {
		if (v > 0) return "pos";
		if (v < 0) return "neg";
		return "";
	}

	let showPopover = $state(false);
	let scoreButtonRef: HTMLElement;
	let popoverTop = $state(0);
	let popoverLeft = $state(0);

	function togglePopover(e: MouseEvent) {
		if (!showPopover) {
			const rect = scoreButtonRef.getBoundingClientRect();
			// Position the popover below and to the left to avoid edge clipping
			popoverTop = rect.bottom + 8;
			popoverLeft = rect.right - 280; // 280px is popover width
			showPopover = true;
		} else {
			showPopover = false;
		}
	}

	function closePopover(e: MouseEvent) {
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

	// Mock score data
	const mockScoreData = $derived(
		risk ? {
			totalScore: risk.managerScore,
			penaltyApplied: risk.managerScore < 40,
			missingData: risk.managerScore < 40 ? ['expense_ratio'] : [],
			components: [
				{ name: 'Risk-Adjusted Return (Sharpe)', weight: 0.30, score: risk.managerScore * 0.9 },
				{ name: 'Return Consistency', weight: 0.20, score: risk.managerScore * 0.85 },
				{ name: 'Drawdown Control', weight: 0.20, score: risk.managerScore * 1.1 },
				{ name: 'Information Ratio', weight: 0.15, score: risk.managerScore * 1.05 },
				{ name: 'Fee Efficiency', weight: 0.10, score: risk.managerScore * 0.95 },
				{ name: 'Flows Momentum', weight: 0.05, score: risk.managerScore * 1.15 }
			]
		} : null
	);

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
				method: 'POST',
				headers: {
					"Authorization": `Bearer ${token}`
				}
			});

			if (!response.ok) {
				throw new Error('Failed to generate Tear Sheet');
			}

			const blob = await response.blob();
			const url = URL.createObjectURL(blob);
			
			const a = document.createElement('a');
			a.style.display = 'none';
			a.href = url;
			a.download = `${externalId}-tear-sheet.pdf`;
			
			document.body.appendChild(a);
			a.click();
			
			// Cleanup
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
</script>

<div class="rk-root">
	{#if risk && selectedNode}
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
					onkeydown={(e) => { if (e.key === 'Enter') togglePopover(e as any); }}
					role="button"
					tabindex="0"
					aria-haspopup="dialog"
					aria-expanded={showPopover}
				>
					<div class="rk-score-label">FUND SCORE</div>
					<div class="rk-score-val">
						{#if risk.managerScore >= 75}
							<span class="elite">[ ELITE ]</span>
						{:else if risk.managerScore < 40}
							<span class="eviction">[ EVICTION ]</span>
						{:else}
							{fmt(risk.managerScore, 1)}
						{/if}
					</div>
				</div>
				
				<button 
					class="rk-export-btn {isGeneratingPdf ? 'exporting' : ''}" 
					onclick={exportTearSheet} 
					disabled={isGeneratingPdf}
				>
					{isGeneratingPdf ? '[ GENERATING PDF... ]' : '[ EXPORT TEAR SHEET ]'}
				</button>
			</div>
		</div>

		<!-- Risk Statistics -->
		<div class="rk-section">
			<div class="rk-section-title">RISK STATISTICS</div>
			<div class="rk-block">
				<div class="rk-kpi">
					<span class="rk-label">Ann. Return</span>
					<span class="rk-value {pctClass(risk.annReturn)}">{fmt(risk.annReturn)}%</span>
				</div>
				<div class="rk-kpi">
					<span class="rk-label">Ann. Volatility</span>
					<span class="rk-value">{fmt(risk.annVolatility)}%</span>
				</div>
				<div class="rk-kpi">
					<span class="rk-label">Sharpe Ratio</span>
					<span class="rk-value">{fmt(risk.sharpe)}</span>
				</div>
				<div class="rk-kpi">
					<span class="rk-label">Sortino Ratio</span>
					<span class="rk-value">{fmt(risk.sortino)}</span>
				</div>
			</div>
		</div>

		<!-- Drawdown Analysis -->
		<div class="rk-section">
			<div class="rk-section-title">DRAWDOWN ANALYSIS</div>
			<div class="rk-block">
				<div class="rk-kpi">
					<span class="rk-label">Max Drawdown</span>
					<span class="rk-value neg">{fmt(risk.maxDrawdown)}%</span>
				</div>
				<div class="rk-kpi">
					<span class="rk-label">Current Drawdown</span>
					<span class="rk-value neg">{fmt(risk.currentDrawdown)}%</span>
				</div>
				<div class="rk-kpi">
					<span class="rk-label">Longest DD</span>
					<span class="rk-value">{risk.longestDrawdownDays}d</span>
				</div>
			</div>
		</div>

		<!-- Up/Down Capture -->
		<div class="rk-section">
			<div class="rk-section-title">CAPTURE RATIOS</div>
			<div class="rk-block">
				<div class="rk-kpi">
					<span class="rk-label">Up Capture</span>
					<span class="rk-value pos">{fmt(risk.upCapture, 1)}%</span>
				</div>
				<div class="rk-kpi">
					<span class="rk-label">Down Capture</span>
					<span class="rk-value neg">{fmt(risk.downCapture, 1)}%</span>
				</div>
			</div>
		</div>

		<!-- Additional Metrics -->
		<div class="rk-section">
			<div class="rk-section-title">FACTOR EXPOSURE</div>
			<div class="rk-block">
				<div class="rk-kpi">
					<span class="rk-label">Beta</span>
					<span class="rk-value">{fmt(risk.beta)}</span>
				</div>
				<div class="rk-kpi">
					<span class="rk-label">Tracking Error</span>
					<span class="rk-value">{fmt(risk.trackingError)}%</span>
				</div>
				<div class="rk-kpi">
					<span class="rk-label">Information Ratio</span>
					<span class="rk-value {pctClass(risk.infoRatio)}">{fmt(risk.infoRatio)}</span>
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

{#if showPopover && mockScoreData}
	<div 
		class="rk-popover-portal" 
		style="top: {popoverTop}px; left: {popoverLeft}px;"
		onclick={stopPropagation}
		onkeydown={(e) => e.stopPropagation()}
		role="presentation"
	>
		<ScoreBreakdownPopover scoreData={mockScoreData} />
	</div>
{/if}

<style>
	.rk-root {
		display: flex;
		flex-direction: column;
		height: 100%;
		background: #0c1018;
		border-left: 1px solid rgba(255, 255, 255, 0.06);
		font-family: "Urbanist", system-ui, sans-serif;
		overflow-y: auto;
		overflow-x: hidden;
	}

	/* ── Header ───────────────────────────────────── */
	.rk-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 12px 14px 8px;
		border-bottom: 1px solid rgba(255, 255, 255, 0.06);
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
		font-size: 14px;
		font-weight: 800;
		color: #e2e8f0;
		letter-spacing: 0.04em;
	}

	.rk-node-type {
		font-size: 9px;
		font-weight: 600;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: #5a6577;
	}

	.rk-score-btn {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 4px 8px;
		border-radius: 4px;
		cursor: pointer;
		transition: background 150ms ease;
		user-select: none;
		background: transparent;
	}

	.rk-score-btn:hover {
		background: rgba(255, 255, 255, 0.05);
	}

	.rk-score-label {
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.05em;
		color: #64748b;
	}

	.rk-score-val {
		font-size: 14px;
		font-weight: 800;
		color: #ffffff;
		font-variant-numeric: tabular-nums;
		font-family: monospace;
	}

	.elite { color: #2d7ef7; font-size: 11px; letter-spacing: 0.05em; }
	.eviction { color: #ca8a04; font-size: 11px; letter-spacing: 0.05em; }

	.rk-export-btn {
		background: transparent;
		border: 1px solid #1e293b;
		color: #94a3b8;
		font-family: monospace;
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.05em;
		padding: 4px 8px;
		cursor: pointer;
		transition: all 150ms ease;
		outline: none;
	}

	.rk-export-btn:hover:not(:disabled) {
		border-color: #2d7ef7;
		color: #2d7ef7;
	}

	.rk-export-btn:disabled {
		cursor: not-allowed;
	}

	.rk-export-btn.exporting {
		color: #ca8a04;
		border-color: #ca8a04;
		animation: pulseBorder 1.5s infinite alternate;
	}

	@keyframes pulseBorder {
		0% { border-color: rgba(202, 138, 4, 0.4); color: rgba(202, 138, 4, 0.8); }
		100% { border-color: rgba(202, 138, 4, 1); color: #ca8a04; }
	}

	/* ── Section ──────────────────────────────────── */
	.rk-section {
		padding: 0 10px;
		margin-bottom: 2px;
	}

	.rk-section-title {
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.1em;
		color: #3a4455;
		text-transform: uppercase;
		padding: 10px 4px 4px;
	}

	.rk-block {
		background: #0e1320;
		border-radius: 3px;
		padding: 8px 10px;
		display: flex;
		flex-direction: column;
		gap: 6px;
	}

	/* ── KPI row ──────────────────────────────────── */
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
		color: #5a6577;
		text-transform: uppercase;
		flex-shrink: 0;
	}

	.rk-value {
		font-size: 16px;
		font-weight: 800;
		color: #e2e8f0;
		font-variant-numeric: tabular-nums;
		text-align: right;
	}

	.pos { color: #22c55e; }
	.neg { color: #ef4444; }

	/* ── Empty ────────────────────────────────────── */
	.rk-empty {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 8px;
		height: 100%;
		color: #3a4455;
	}

	.rk-empty-icon {
		font-size: 20px;
		opacity: 0.3;
	}

	.rk-empty-text {
		font-family: "Urbanist", system-ui, sans-serif;
		font-size: 11px;
		letter-spacing: 0.04em;
	}

	/* ── Popover Portal ───────────────────────────── */
	.rk-popover-portal {
		position: fixed;
		z-index: 1000;
	}
</style>


