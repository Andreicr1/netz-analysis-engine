<!--
  TradeConfirmationDialog — native <dialog> for trade execution.

  Summarises the order batch and requires explicit "Confirm" to fire.
  Shows holdingsVersion for optimistic lock transparency.
  Displays execution result (success/error) inline after fire.
-->
<script lang="ts">
	import { onMount } from "svelte";
	import type { OverlapResultRead } from "./LiveWorkbenchShell.svelte";

	interface Props {
		portfolioName: string;
		buyCount: number;
		sellCount: number;
		totalOrders: number;
		turnoverPct: number;
		holdingsVersion: number;
		executing: boolean;
		execResult: { ok: boolean; message: string } | null;
		onConfirm: () => void;
		onClose: () => void;
		overlapResult?: OverlapResultRead | null;
	}

	let {
		portfolioName,
		buyCount,
		sellCount,
		totalOrders,
		turnoverPct,
		holdingsVersion,
		executing,
		execResult,
		onConfirm,
		onClose,
		overlapResult = null,
	}: Props = $props();

	let dialogEl: HTMLDialogElement | undefined = $state();

	onMount(() => {
		dialogEl?.showModal();
	});

	function handleClose() {
		dialogEl?.close();
		onClose();
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === "Escape") {
			e.preventDefault();
			handleClose();
		}
	}

	function handleBackdropClick(e: MouseEvent) {
		if (e.target === dialogEl) handleClose();
	}

	function fmtPct(n: number): string {
		return (n * 100).toFixed(2) + "%";
	}
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<dialog
	bind:this={dialogEl}
	class="tcd-dialog"
	onkeydown={handleKeydown}
	onclick={handleBackdropClick}
>
	<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
	<div class="tcd-content" onclick={(e) => e.stopPropagation()}>
		<div class="tcd-header">
			<span class="tcd-title">CONFIRM EXECUTION</span>
			<button
				type="button"
				class="tcd-close"
				onclick={handleClose}
				aria-label="Close"
			>&#x2715;</button>
		</div>

		<div class="tcd-body">
			<div class="tcd-row">
				<span class="tcd-label">Portfolio</span>
				<span class="tcd-value">{portfolioName}</span>
			</div>
			<div class="tcd-row">
				<span class="tcd-label">Orders</span>
				<span class="tcd-value">
					{totalOrders} total
					{#if buyCount > 0}
						<span class="tcd-buy">{buyCount} BUY</span>
					{/if}
					{#if sellCount > 0}
						<span class="tcd-sell">{sellCount} SELL</span>
					{/if}
				</span>
			</div>
			<div class="tcd-row">
				<span class="tcd-label">Est. Turnover</span>
				<span class="tcd-value tcd-mono">{fmtPct(turnoverPct)}</span>
			</div>
			<div class="tcd-row">
				<span class="tcd-label">Holdings Version</span>
				<span class="tcd-value tcd-mono">v{holdingsVersion}</span>
			</div>

			{#if overlapResult && overlapResult.breaches.length > 0}
				<div class="tcd-warning-box">
					<span class="tcd-warning-title">[ ! PORTFOLIO OVERLAP DETECTED ]</span>
					{#each overlapResult.breaches as breach}
						<span class="tcd-warning-text">
							&gt; {(breach.total_exposure_pct * 100).toFixed(1)}% {breach.issuer_name ?? 'Unknown'} ({breach.cusip})
						</span>
					{/each}
				</div>
			{/if}

			{#if execResult}
				<div
					class="tcd-result"
					class:tcd-result--ok={execResult.ok}
					class:tcd-result--err={!execResult.ok}
				>
					{execResult.message}
				</div>
			{/if}
		</div>

		<div class="tcd-actions">
			{#if execResult?.ok}
				<button type="button" class="tcd-btn tcd-btn--done" onclick={handleClose}>
					Done
				</button>
			{:else}
				<button type="button" class="tcd-btn tcd-btn--cancel" onclick={handleClose}>
					Cancel
				</button>
				<button
					type="button"
					class="tcd-btn tcd-btn--confirm"
					disabled={executing}
					onclick={onConfirm}
				>
					{executing ? "Executing..." : "Confirm"}
				</button>
			{/if}
		</div>
	</div>
</dialog>

<style>
	/* ── Dialog backdrop + box ────────────────────────────── */
	.tcd-dialog {
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
	.tcd-dialog::backdrop {
		background: rgba(0, 0, 0, 0.65);
	}

	.tcd-content {
		width: 380px;
		background: #0e1320;
		border: 1px solid rgba(255, 255, 255, 0.12);
		box-shadow: 0 12px 40px rgba(0, 0, 0, 0.6);
		font-family: "Urbanist", system-ui, sans-serif;
	}

	/* ── Header ──────────────────────────────────────────── */
	.tcd-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 10px 14px;
		border-bottom: 1px solid rgba(255, 255, 255, 0.08);
	}
	.tcd-title {
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.12em;
		color: #c8d0dc;
	}
	.tcd-close {
		appearance: none;
		font-size: 12px;
		color: #5a6577;
		background: transparent;
		border: none;
		cursor: pointer;
		padding: 2px;
	}
	.tcd-close:hover { color: #c8d0dc; }

	/* ── Body ────────────────────────────────────────────── */
	.tcd-body {
		padding: 12px 14px;
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.tcd-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}
	.tcd-label {
		font-size: 10px;
		font-weight: 600;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: #5a6577;
	}
	.tcd-value {
		font-size: 12px;
		font-weight: 600;
		color: #c8d0dc;
		display: flex;
		align-items: center;
		gap: 6px;
	}
	.tcd-mono {
		font-family: "JetBrains Mono", "SF Mono", monospace;
		font-variant-numeric: tabular-nums;
	}

	.tcd-buy {
		font-size: 10px;
		font-weight: 700;
		color: #22c55e;
		padding: 1px 5px;
		background: rgba(34, 197, 94, 0.10);
	}
	.tcd-sell {
		font-size: 10px;
		font-weight: 700;
		color: #ef4444;
		padding: 1px 5px;
		background: rgba(239, 68, 68, 0.10);
	}

	/* ── Warning Box ─────────────────────────────────────── */
	.tcd-warning-box {
		margin-top: 8px;
		padding: 8px;
		background: rgba(202, 138, 4, 0.06);
		border: 1px solid rgba(202, 138, 4, 0.25);
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	.tcd-warning-title {
		font-family: "JetBrains Mono", "SF Mono", monospace;
		font-size: 10px;
		font-weight: 700;
		color: #ca8a04;
		letter-spacing: 0.05em;
	}
	.tcd-warning-text {
		font-family: "JetBrains Mono", "SF Mono", monospace;
		font-size: 10px;
		color: #eab308;
		font-weight: 600;
	}

	/* ── Result banner ───────────────────────────────────── */
	.tcd-result {
		padding: 8px 10px;
		font-size: 11px;
		font-weight: 600;
	}
	.tcd-result--ok {
		color: #22c55e;
		background: rgba(34, 197, 94, 0.08);
		border: 1px solid rgba(34, 197, 94, 0.20);
	}
	.tcd-result--err {
		color: #ef4444;
		background: rgba(239, 68, 68, 0.08);
		border: 1px solid rgba(239, 68, 68, 0.20);
	}

	/* ── Actions ─────────────────────────────────────────── */
	.tcd-actions {
		display: flex;
		gap: 8px;
		padding: 10px 14px;
		border-top: 1px solid rgba(255, 255, 255, 0.06);
		justify-content: flex-end;
	}

	.tcd-btn {
		appearance: none;
		padding: 6px 16px;
		font-family: inherit;
		font-size: 11px;
		font-weight: 700;
		letter-spacing: 0.02em;
		border: none;
		cursor: pointer;
		transition: background 80ms;
	}
	.tcd-btn:focus-visible {
		outline: 2px solid #2d7ef7;
		outline-offset: 2px;
	}
	.tcd-btn--cancel {
		color: #8896a8;
		background: rgba(255, 255, 255, 0.06);
	}
	.tcd-btn--cancel:hover { background: rgba(255, 255, 255, 0.10); }

	.tcd-btn--confirm {
		color: #ffffff;
		background: #2d7ef7;
	}
	.tcd-btn--confirm:hover:not(:disabled) { background: #3b8bff; }
	.tcd-btn--confirm:disabled { opacity: 0.4; cursor: not-allowed; }

	.tcd-btn--done {
		color: #ffffff;
		background: #22c55e;
	}
	.tcd-btn--done:hover { background: #2dd870; }
</style>
