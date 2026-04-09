<!--
  TerminalOmsPanel — execution order rail (grid-area: oms).

  Extreme density: 11px body, 9px labels, 4px card padding.
  Generates BUY/SELL orders from target vs actual weight deltas.
  Footer: dormant venue selector + "Approve & Execute" button.
-->
<script lang="ts">
	import TradeConfirmationDialog from "./TradeConfirmationDialog.svelte";
	import type { InstrumentWeight } from "$lib/types/model-portfolio";

	/** Actual holding from the OMS endpoint. */
	export interface ActualHolding {
		instrument_id: string;
		fund_name: string;
		block_id: string;
		weight: number;
	}

	interface Props {
		portfolioId: string;
		portfolioName: string;
		targetFunds: InstrumentWeight[];
		actualHoldings: ActualHolding[];
		holdingsVersion: number;
	}

	let {
		portfolioId,
		portfolioName,
		targetFunds,
		actualHoldings,
		holdingsVersion,
	}: Props = $props();

	// ── Derive order list from target vs actual ───────────────
	interface OrderLine {
		instrumentId: string;
		fundName: string;
		action: "BUY" | "SELL";
		deltaWeight: number; // absolute
		targetWeight: number;
		actualWeight: number;
	}

	const orders = $derived.by<OrderLine[]>(() => {
		const actualMap = new Map(actualHoldings.map((h) => [h.instrument_id, h.weight]));
		const lines: OrderLine[] = [];
		for (const f of targetFunds) {
			const actual = actualMap.get(f.instrument_id) ?? 0;
			const delta = f.weight - actual;
			if (Math.abs(delta) < 0.001) continue; // skip negligible
			lines.push({
				instrumentId: f.instrument_id,
				fundName: f.fund_name,
				action: delta > 0 ? "BUY" : "SELL",
				deltaWeight: Math.abs(delta),
				targetWeight: f.weight,
				actualWeight: actual,
			});
		}
		// Sort: BUY first, then by delta desc
		lines.sort((a, b) => {
			if (a.action !== b.action) return a.action === "BUY" ? -1 : 1;
			return b.deltaWeight - a.deltaWeight;
		});
		return lines;
	});

	const buyCount = $derived(orders.filter((o) => o.action === "BUY").length);
	const sellCount = $derived(orders.filter((o) => o.action === "SELL").length);
	const totalTurnover = $derived(
		orders.reduce((sum, o) => sum + o.deltaWeight, 0),
	);

	// ── Confirmation dialog ───────────────────────────────────
	let showConfirm = $state(false);
	let executing = $state(false);
	let execResult = $state<{ ok: boolean; message: string } | null>(null);

	function openConfirm() {
		execResult = null;
		showConfirm = true;
	}

	async function handleConfirm() {
		executing = true;
		execResult = null;
		// Simulated execution — will be wired to real API later
		await new Promise((r) => setTimeout(r, 800));
		// Simulate success
		execResult = { ok: true, message: `${orders.length} trades executed (simulated)` };
		executing = false;
	}

	function closeConfirm() {
		showConfirm = false;
	}

	function fmtPct(n: number): string {
		return (n * 100).toFixed(2) + "%";
	}
</script>

<div class="oms-root">
	<!-- Header -->
	<div class="oms-header">
		<span class="oms-title">ORDER BOOK</span>
		<span class="oms-count">{orders.length}</span>
	</div>

	<!-- Order list (scrollable) -->
	<div class="oms-list">
		{#if orders.length === 0}
			<div class="oms-empty">No rebalance orders</div>
		{:else}
			{#each orders as order}
				<div class="oms-card">
					<div class="oms-card-top">
						<span
							class="oms-action"
							class:oms-buy={order.action === "BUY"}
							class:oms-sell={order.action === "SELL"}
						>{order.action}</span>
						<span class="oms-card-name" title={order.fundName}>
							{order.fundName}
						</span>
					</div>
					<div class="oms-card-bottom">
						<span class="oms-card-label">delta</span>
						<span class="oms-card-value">{fmtPct(order.deltaWeight)}</span>
						<span class="oms-card-label">target</span>
						<span class="oms-card-value">{fmtPct(order.targetWeight)}</span>
					</div>
				</div>
			{/each}
		{/if}
	</div>

	<!-- Footer -->
	<div class="oms-footer">
		<div class="oms-venue">
			<span class="oms-venue-label">Venue</span>
			<span class="oms-venue-value">Simulated</span>
		</div>
		<button
			type="button"
			class="oms-execute-btn"
			disabled={orders.length === 0}
			onclick={openConfirm}
		>
			Approve &amp; Execute
		</button>
	</div>
</div>

{#if showConfirm}
	<TradeConfirmationDialog
		{portfolioName}
		{buyCount}
		{sellCount}
		totalOrders={orders.length}
		turnoverPct={totalTurnover}
		{holdingsVersion}
		{executing}
		{execResult}
		onConfirm={handleConfirm}
		onClose={closeConfirm}
	/>
{/if}

<style>
	.oms-root {
		display: flex;
		flex-direction: column;
		width: 100%;
		height: 100%;
		min-height: 0;
		overflow: hidden;
		font-family: "Urbanist", system-ui, sans-serif;
	}

	/* ── Header ──────────────────────────────────────────── */
	.oms-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		flex-shrink: 0;
		height: 30px;
		padding: 0 10px;
		border-bottom: 1px solid rgba(255, 255, 255, 0.06);
	}
	.oms-title {
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.12em;
		text-transform: uppercase;
		color: #5a6577;
	}
	.oms-count {
		font-family: "JetBrains Mono", "SF Mono", monospace;
		font-size: 10px;
		font-weight: 700;
		color: #c8d0dc;
		background: rgba(255, 255, 255, 0.06);
		padding: 1px 6px;
	}

	/* ── Scrollable order list ────────────────────────────── */
	.oms-list {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		padding: 4px 6px;
		display: flex;
		flex-direction: column;
		gap: 3px;
	}

	.oms-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 100%;
		font-size: 11px;
		color: #3d4654;
	}

	/* ── Order card ──────────────────────────────────────── */
	.oms-card {
		padding: 4px 6px;
		background: rgba(255, 255, 255, 0.02);
		border: 1px solid rgba(255, 255, 255, 0.05);
	}
	.oms-card:hover {
		background: rgba(255, 255, 255, 0.04);
		border-color: rgba(255, 255, 255, 0.08);
	}

	.oms-card-top {
		display: flex;
		align-items: center;
		gap: 6px;
	}

	.oms-action {
		flex-shrink: 0;
		font-family: "JetBrains Mono", "SF Mono", monospace;
		font-size: 9px;
		font-weight: 800;
		letter-spacing: 0.06em;
		padding: 1px 5px;
	}
	.oms-buy {
		color: #22c55e;
		background: rgba(34, 197, 94, 0.10);
		border: 1px solid rgba(34, 197, 94, 0.20);
	}
	.oms-sell {
		color: #ef4444;
		background: rgba(239, 68, 68, 0.10);
		border: 1px solid rgba(239, 68, 68, 0.20);
	}

	.oms-card-name {
		font-size: 11px;
		font-weight: 500;
		color: #c8d0dc;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		min-width: 0;
	}

	.oms-card-bottom {
		display: flex;
		align-items: center;
		gap: 6px;
		margin-top: 2px;
		font-family: "JetBrains Mono", "SF Mono", monospace;
		font-variant-numeric: tabular-nums;
	}
	.oms-card-label {
		font-size: 9px;
		font-weight: 600;
		color: #3d4654;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.oms-card-value {
		font-size: 10px;
		font-weight: 600;
		color: #8896a8;
	}

	/* ── Footer ──────────────────────────────────────────── */
	.oms-footer {
		flex-shrink: 0;
		display: flex;
		flex-direction: column;
		gap: 6px;
		padding: 8px 8px;
		border-top: 1px solid rgba(255, 255, 255, 0.06);
	}

	.oms-venue {
		display: flex;
		align-items: center;
		justify-content: space-between;
		opacity: 0.4;
	}
	.oms-venue-label {
		font-size: 9px;
		font-weight: 600;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: #5a6577;
	}
	.oms-venue-value {
		font-size: 10px;
		font-weight: 600;
		color: #8896a8;
		padding: 2px 8px;
		border: 1px solid rgba(255, 255, 255, 0.08);
	}

	.oms-execute-btn {
		appearance: none;
		width: 100%;
		height: 32px;
		font-family: inherit;
		font-size: 11px;
		font-weight: 700;
		letter-spacing: 0.04em;
		color: #ffffff;
		background: #2d7ef7;
		border: none;
		cursor: pointer;
		transition: background 80ms;
	}
	.oms-execute-btn:hover:not(:disabled) {
		background: #3b8bff;
	}
	.oms-execute-btn:disabled {
		opacity: 0.3;
		cursor: not-allowed;
	}
	.oms-execute-btn:focus-visible {
		outline: 2px solid #2d7ef7;
		outline-offset: 2px;
	}
</style>
