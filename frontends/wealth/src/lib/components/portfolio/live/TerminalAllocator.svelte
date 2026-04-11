<!--
  TerminalAllocator — EDIT mode right panel (replaces OMS).

  Lists draftHoldings with compact numeric inputs for target weight.
  Shows running total with red/green coloring when != 100%.
  Each row has a remove [x] button.
-->
<script lang="ts">
	import { formatNumber } from "@investintell/ui";
	import { goto } from "$app/navigation";
	import type { DraftHolding } from "./LiveWorkbenchShell.svelte";

	interface Props {
		draftHoldings: DraftHolding[];
		onUpdateWeight: (instrumentId: string, weight: number) => void;
		onRemove: (instrumentId: string) => void;
	}

	let { draftHoldings, onUpdateWeight, onRemove }: Props = $props();

	const totalWeight = $derived(
		draftHoldings.reduce((sum, h) => sum + h.targetWeight, 0),
	);

	const isValid = $derived(
		draftHoldings.length > 0 && Math.abs(totalWeight - 100) < 0.01,
	);

	const totalClass = $derived.by(() => {
		if (draftHoldings.length === 0) return "al-total--empty";
		if (Math.abs(totalWeight - 100) < 0.01) return "al-total--valid";
		return "al-total--invalid";
	});

	function handleWeightInput(instrumentId: string, e: Event) {
		const target = e.target as HTMLInputElement;
		const val = parseFloat(target.value);
		onUpdateWeight(instrumentId, isNaN(val) ? 0 : val);
	}

	function goToOptimizer() {
		void goto("/portfolio");
	}
</script>

<div class="al-root">
	<div class="al-header">
		<span class="al-title">ALLOCATOR (MANUAL)</span>
		<span class="al-count">{draftHoldings.length}</span>
	</div>

	<div class="al-list">
		{#if draftHoldings.length === 0}
			<div class="al-empty">
				Add instruments from the Approved Universe panel
			</div>
		{:else}
			{#each draftHoldings as holding}
				<div class="al-card">
					<div class="al-card-top">
						<span class="al-card-name" title={holding.fund_name}>
							{holding.fund_name}
						</span>
						<button
							type="button"
							class="al-remove-btn"
							onclick={() => onRemove(holding.instrument_id)}
							title="Remove from draft"
							aria-label="Remove {holding.fund_name}"
						>&#x2715;</button>
					</div>
					<div class="al-card-bottom">
						<span class="al-card-label">Target %</span>
						<input
							type="number"
							class="al-weight-input"
							min="0"
							max="100"
							step="0.5"
							value={holding.targetWeight}
							oninput={(e) => handleWeightInput(holding.instrument_id, e)}
						/>
					</div>
				</div>
			{/each}
		{/if}
	</div>

	<!-- Footer: total weight -->
	<div class="al-footer">
		<div class="al-total-row">
			<span class="al-total-label">TOTAL</span>
			<span class="al-total-value {totalClass}">
				{formatNumber(totalWeight, 1)}%
			</span>
		</div>
		{#if draftHoldings.length > 0 && Math.abs(totalWeight - 100) >= 0.01}
			<div class="al-total-hint">
				{totalWeight < 100
					? `${formatNumber(100 - totalWeight, 1)}% remaining`
					: `${formatNumber(totalWeight - 100, 1)}% over`}
			</div>
		{/if}
		
		<button class="al-opt-btn" onclick={goToOptimizer}>
			USE CLARABEL OPTIMIZER &rarr;
		</button>
	</div>
</div>

<style>
	.al-root {
		display: flex;
		flex-direction: column;
		width: 100%;
		height: 100%;
		min-height: 0;
		overflow: hidden;
		font-family: "Urbanist", system-ui, sans-serif;
	}

	.al-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		flex-shrink: 0;
		height: 30px;
		padding: 0 10px;
		border-bottom: 1px solid rgba(255, 255, 255, 0.06);
	}
	.al-title {
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.12em;
		text-transform: uppercase;
		color: #2d7ef7;
	}
	.al-count {
		font-family: "JetBrains Mono", "SF Mono", monospace;
		font-size: 10px;
		font-weight: 700;
		color: #c8d0dc;
		background: rgba(255, 255, 255, 0.06);
		padding: 1px 6px;
	}

	/* ── Scrollable card list ────────────────────────────────── */
	.al-list {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		padding: 4px 6px;
		display: flex;
		flex-direction: column;
		gap: 3px;
	}

	.al-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		text-align: center;
		height: 100%;
		font-size: 11px;
		color: #3d4654;
		padding: 16px;
		line-height: 1.4;
	}

	/* ── Holding card ────────────────────────────────────────── */
	.al-card {
		padding: 5px 6px;
		background: rgba(255, 255, 255, 0.02);
		border: 1px solid rgba(255, 255, 255, 0.05);
	}
	.al-card:hover {
		background: rgba(255, 255, 255, 0.04);
		border-color: rgba(255, 255, 255, 0.08);
	}

	.al-card-top {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 4px;
	}
	.al-card-name {
		font-size: 11px;
		font-weight: 500;
		color: #c8d0dc;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		min-width: 0;
		flex: 1;
	}
	.al-remove-btn {
		appearance: none;
		flex-shrink: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		width: 18px;
		height: 18px;
		padding: 0;
		font-size: 10px;
		color: #5a6577;
		background: transparent;
		border: 1px solid transparent;
		cursor: pointer;
		transition: color 60ms, background 60ms;
	}
	.al-remove-btn:hover {
		color: #ef4444;
		background: rgba(239, 68, 68, 0.08);
		border-color: rgba(239, 68, 68, 0.20);
	}

	.al-card-bottom {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
		margin-top: 3px;
	}
	.al-card-label {
		font-size: 9px;
		font-weight: 600;
		color: #3d4654;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.al-weight-input {
		width: 72px;
		height: 24px;
		padding: 0 6px;
		font-family: "JetBrains Mono", "SF Mono", monospace;
		font-size: 11px;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		color: #c8d0dc;
		background: rgba(255, 255, 255, 0.04);
		border: 1px solid rgba(255, 255, 255, 0.10);
		text-align: right;
		outline: none;
		transition: border-color 80ms;
	}
	.al-weight-input:focus {
		border-color: rgba(45, 126, 247, 0.5);
	}
	/* Hide spinner arrows */
	.al-weight-input::-webkit-inner-spin-button,
	.al-weight-input::-webkit-outer-spin-button {
		-webkit-appearance: none;
		margin: 0;
	}

	/* ── Footer ──────────────────────────────────────────────── */
	.al-footer {
		flex-shrink: 0;
		padding: 8px 10px;
		border-top: 1px solid rgba(255, 255, 255, 0.06);
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.al-total-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}
	.al-total-label {
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.10em;
		color: #5a6577;
	}
	.al-total-value {
		font-family: "JetBrains Mono", "SF Mono", monospace;
		font-size: 14px;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
	}
	.al-total--empty { color: #3d4654; }
	.al-total--valid { color: #22c55e; }
	.al-total--invalid { color: #f59e0b; }

	.al-total-hint {
		font-size: 9px;
		font-weight: 500;
		color: #5a6577;
		text-align: right;
	}

	.al-opt-btn {
		width: 100%;
		padding: 8px;
		background: rgba(45, 126, 247, 0.1);
		border: 1px solid rgba(45, 126, 247, 0.3);
		color: #2d7ef7;
		font-family: monospace;
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.05em;
		cursor: pointer;
		transition: all 150ms ease;
		text-align: center;
		outline: none;
		margin-top: 4px;
	}

	.al-opt-btn:hover {
		background: rgba(45, 126, 247, 0.2);
		border-color: #2d7ef7;
		color: #ffffff;
	}
</style>
