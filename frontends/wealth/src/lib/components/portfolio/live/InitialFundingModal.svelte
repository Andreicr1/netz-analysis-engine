<!--
  InitialFundingModal — STP Initial Funding dialog.

  Asks for Initial AUM ($), computes BUY orders from draftHoldings,
  then invokes TradeConfirmationDialog for the final confirm/cancel.
-->
<script lang="ts">
	import { onMount } from "svelte";
	import TradeConfirmationDialog from "./TradeConfirmationDialog.svelte";
	import type { DraftHolding } from "./LiveWorkbenchShell.svelte";

	interface Props {
		draftHoldings: DraftHolding[];
		portfolioName: string;
		onComplete: () => void;
		onCancel: () => void;
	}

	let { draftHoldings, portfolioName, onComplete, onCancel }: Props = $props();

	let dialogEl: HTMLDialogElement | undefined = $state();
	let aumInput = $state("");
	let showTradeConfirm = $state(false);
	let executing = $state(false);
	let execResult = $state<{ ok: boolean; message: string } | null>(null);

	onMount(() => {
		dialogEl?.showModal();
	});

	const aumValue = $derived(() => {
		const parsed = parseFloat(aumInput.replace(/,/g, ""));
		return isNaN(parsed) ? 0 : parsed;
	});

	const totalWeight = $derived(
		draftHoldings.reduce((sum, h) => sum + h.targetWeight, 0),
	);

	const isReady = $derived(
		aumValue() > 0 && draftHoldings.length > 0 && Math.abs(totalWeight - 100) < 0.01,
	);

	// Computed BUY orders from draft + AUM
	const generatedOrders = $derived.by(() => {
		const aum = aumValue();
		if (aum <= 0) return [];
		return draftHoldings
			.filter((h) => h.targetWeight > 0)
			.map((h) => ({
				instrumentId: h.instrument_id,
				fundName: h.fund_name,
				blockId: h.block_id,
				action: "BUY" as const,
				targetWeight: h.targetWeight / 100,
				tradeValue: Math.round((h.targetWeight / 100) * aum * 100) / 100,
			}));
	});

	const buyCount = $derived(generatedOrders.length);
	const totalTurnover = $derived(
		generatedOrders.reduce((sum, o) => sum + o.targetWeight, 0),
	);

	function handleProceed() {
		showTradeConfirm = true;
	}

	async function handleTradeConfirm() {
		executing = true;
		execResult = null;
		// Simulated API call
		await new Promise((r) => setTimeout(r, 800));
		execResult = {
			ok: true,
			message: `${generatedOrders.length} BUY orders executed. Portfolio funded with $${formatNumber(aumValue())}.`,
		};
		executing = false;
	}

	function handleTradeDone() {
		showTradeConfirm = false;
		onComplete();
	}

	function handleTradeClose() {
		if (execResult?.ok) {
			handleTradeDone();
			return;
		}
		showTradeConfirm = false;
	}

	function handleClose() {
		dialogEl?.close();
		onCancel();
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === "Escape") {
			e.preventDefault();
			if (showTradeConfirm) return;
			handleClose();
		}
	}

	function handleBackdropClick(e: MouseEvent) {
		if (e.target === dialogEl && !showTradeConfirm) handleClose();
	}

	function formatNumber(n: number): string {
		return n.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
	}

	function formatCurrency(n: number): string {
		return "$" + formatNumber(n);
	}
</script>

{#if !showTradeConfirm}
	<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
	<dialog
		bind:this={dialogEl}
		class="ifm-dialog"
		onkeydown={handleKeydown}
		onclick={handleBackdropClick}
	>
		<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
		<div class="ifm-content" onclick={(e) => e.stopPropagation()}>
			<div class="ifm-header">
				<span class="ifm-title">INITIAL FUNDING</span>
				<button
					type="button"
					class="ifm-close"
					onclick={handleClose}
					aria-label="Close"
				>&#x2715;</button>
			</div>

			<div class="ifm-body">
				<p class="ifm-desc">
					Enter the initial AUM to calculate buy orders for <strong>{portfolioName}</strong>.
				</p>

				<div class="ifm-field">
					<label class="ifm-label" for="aum-input">Initial AUM ($)</label>
					<input
						id="aum-input"
						type="text"
						class="ifm-aum-input"
						placeholder="10,000,000"
						bind:value={aumInput}
					/>
				</div>

				{#if aumValue() > 0 && generatedOrders.length > 0}
					<div class="ifm-preview">
						<div class="ifm-preview-title">ORDER PREVIEW</div>
						{#each generatedOrders as order}
							<div class="ifm-order-row">
								<span class="ifm-order-action">BUY</span>
								<span class="ifm-order-name" title={order.fundName}>{order.fundName}</span>
								<span class="ifm-order-value">{formatCurrency(order.tradeValue)}</span>
							</div>
						{/each}
						<div class="ifm-order-total">
							<span class="ifm-order-total-label">Total</span>
							<span class="ifm-order-total-value">{formatCurrency(aumValue())}</span>
						</div>
					</div>
				{/if}
			</div>

			<div class="ifm-actions">
				<button type="button" class="ifm-btn ifm-btn--cancel" onclick={handleClose}>
					Cancel
				</button>
				<button
					type="button"
					class="ifm-btn ifm-btn--proceed"
					disabled={!isReady}
					onclick={handleProceed}
				>
					Generate Orders
				</button>
			</div>
		</div>
	</dialog>
{:else}
	<TradeConfirmationDialog
		{portfolioName}
		{buyCount}
		sellCount={0}
		totalOrders={buyCount}
		turnoverPct={totalTurnover}
		holdingsVersion={1}
		{executing}
		{execResult}
		onConfirm={handleTradeConfirm}
		onClose={handleTradeClose}
	/>
{/if}

<style>
	.ifm-dialog {
		position: fixed;
		inset: 0;
		z-index: 200;
		display: flex;
		align-items: center;
		justify-content: center;
		width: 100%;
		height: 100%;
		padding: 0;
		margin: 0;
		border: none;
		background: transparent;
		max-width: 100%;
		max-height: 100%;
	}
	.ifm-dialog::backdrop {
		background: rgba(0, 0, 0, 0.65);
	}

	.ifm-content {
		width: 440px;
		max-height: 80vh;
		overflow-y: auto;
		background: #0e1320;
		border: 1px solid rgba(255, 255, 255, 0.12);
		box-shadow: 0 12px 40px rgba(0, 0, 0, 0.6);
		font-family: "Urbanist", system-ui, sans-serif;
	}

	.ifm-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 10px 14px;
		border-bottom: 1px solid rgba(255, 255, 255, 0.08);
	}
	.ifm-title {
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.12em;
		color: #2d7ef7;
	}
	.ifm-close {
		appearance: none;
		font-size: 12px;
		color: #5a6577;
		background: transparent;
		border: none;
		cursor: pointer;
		padding: 2px;
	}
	.ifm-close:hover { color: #c8d0dc; }

	.ifm-body {
		padding: 14px;
		display: flex;
		flex-direction: column;
		gap: 12px;
	}

	.ifm-desc {
		margin: 0;
		font-size: 12px;
		color: #8896a8;
		line-height: 1.4;
	}
	.ifm-desc strong {
		color: #c8d0dc;
		font-weight: 600;
	}

	.ifm-field {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	.ifm-label {
		font-size: 10px;
		font-weight: 600;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: #5a6577;
	}
	.ifm-aum-input {
		height: 36px;
		padding: 0 10px;
		font-family: "JetBrains Mono", "SF Mono", monospace;
		font-size: 16px;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		color: #ffffff;
		background: rgba(255, 255, 255, 0.04);
		border: 1px solid rgba(255, 255, 255, 0.12);
		outline: none;
		transition: border-color 80ms;
	}
	.ifm-aum-input:focus {
		border-color: rgba(45, 126, 247, 0.5);
	}
	.ifm-aum-input::placeholder {
		color: #3d4654;
		font-weight: 400;
	}

	/* ── Order preview ──────────────────────────────────────── */
	.ifm-preview {
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: 8px;
		background: rgba(255, 255, 255, 0.02);
		border: 1px solid rgba(255, 255, 255, 0.06);
	}
	.ifm-preview-title {
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.10em;
		color: #5a6577;
		margin-bottom: 4px;
	}
	.ifm-order-row {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 2px 0;
	}
	.ifm-order-action {
		font-family: "JetBrains Mono", "SF Mono", monospace;
		font-size: 9px;
		font-weight: 800;
		color: #22c55e;
		background: rgba(34, 197, 94, 0.10);
		padding: 1px 5px;
		letter-spacing: 0.04em;
		flex-shrink: 0;
	}
	.ifm-order-name {
		flex: 1;
		min-width: 0;
		font-size: 11px;
		font-weight: 500;
		color: #c8d0dc;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.ifm-order-value {
		flex-shrink: 0;
		font-family: "JetBrains Mono", "SF Mono", monospace;
		font-size: 10px;
		font-weight: 600;
		color: #22c55e;
		font-variant-numeric: tabular-nums;
	}
	.ifm-order-total {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-top: 4px;
		padding-top: 4px;
		border-top: 1px solid rgba(255, 255, 255, 0.06);
	}
	.ifm-order-total-label {
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.08em;
		color: #5a6577;
		text-transform: uppercase;
	}
	.ifm-order-total-value {
		font-family: "JetBrains Mono", "SF Mono", monospace;
		font-size: 12px;
		font-weight: 700;
		color: #ffffff;
		font-variant-numeric: tabular-nums;
	}

	/* ── Actions ─────────────────────────────────────────────── */
	.ifm-actions {
		display: flex;
		gap: 8px;
		padding: 10px 14px;
		border-top: 1px solid rgba(255, 255, 255, 0.06);
		justify-content: flex-end;
	}
	.ifm-btn {
		appearance: none;
		padding: 8px 20px;
		font-family: inherit;
		font-size: 11px;
		font-weight: 700;
		letter-spacing: 0.02em;
		border: none;
		cursor: pointer;
		transition: background 80ms;
	}
	.ifm-btn:focus-visible {
		outline: 2px solid #2d7ef7;
		outline-offset: 2px;
	}
	.ifm-btn--cancel {
		color: #8896a8;
		background: rgba(255, 255, 255, 0.06);
	}
	.ifm-btn--cancel:hover { background: rgba(255, 255, 255, 0.10); }
	.ifm-btn--proceed {
		color: #ffffff;
		background: #2d7ef7;
	}
	.ifm-btn--proceed:hover:not(:disabled) { background: #3b8bff; }
	.ifm-btn--proceed:disabled { opacity: 0.3; cursor: not-allowed; }
</style>
