<!--
  RebalanceSuggestionPanel — Phase 9 OMS integration.

  Reads the drift between target and actual weights and produces
  virtual trade tickets to zero every drift:
    - drift > 0 (overweight) → SELL ticket for the overshoot
    - drift < 0 (underweight) → BUY ticket for the gap

  "Approve & Execute Trades" POSTs to the real backend endpoint
  ``POST /model-portfolios/{id}/execute-trades``. On success, the
  parent shell's ``onTradesExecuted`` callback triggers a re-fetch
  of actual-holdings, zeroing the drift table instantly.

  Per CLAUDE.md: DL16 (formatters from @investintell/ui),
  DL15 (no localStorage — execution state is ephemeral in-memory).
-->
<script lang="ts">
	import { formatPercent } from "@investintell/ui";
	import { blockLabel } from "$lib/constants/blocks";
	import type { InstrumentWeight } from "$lib/types/model-portfolio";

	interface ActualHolding {
		instrument_id: string;
		fund_name: string;
		block_id: string;
		weight: number;
	}

	interface TradeTicket {
		instrumentId: string;
		fundName: string;
		blockId: string;
		action: "BUY" | "SELL";
		deltaPct: number;
	}

	interface Props {
		portfolioId: string;
		portfolioName: string;
		targetFunds: readonly InstrumentWeight[];
		actualHoldings: readonly ActualHolding[];
		loading?: boolean;
		/** Called after a successful trade execution so the parent
		 *  can re-fetch actual holdings and refresh the drift table. */
		onTradesExecuted: () => Promise<void>;
		/** API client post function — injected from the shell so
		 *  this component stays pure of context reads. */
		apiPost: <T>(path: string, body?: unknown) => Promise<T>;
	}

	let {
		portfolioId,
		portfolioName,
		targetFunds,
		actualHoldings,
		loading = false,
		onTradesExecuted,
		apiPost,
	}: Props = $props();

	function printTradeSheet() {
		window.print();
	}

	const printDate = $derived(
		new Date().toLocaleDateString("en-US", {
			year: "numeric",
			month: "long",
			day: "numeric",
			hour: "2-digit",
			minute: "2-digit",
		}),
	);

	const tickets = $derived.by<TradeTicket[]>(() => {
		const actualMap = new Map(
			actualHoldings.map((h) => [h.instrument_id, h]),
		);
		return targetFunds
			.map((f) => {
				const actual = actualMap.get(f.instrument_id);
				const actualWeight = actual?.weight ?? f.weight;
				const drift = actualWeight - f.weight;
				if (Math.abs(drift) < 0.001) return null;
				return {
					instrumentId: f.instrument_id,
					fundName: f.fund_name,
					blockId: f.block_id,
					action: drift > 0 ? ("SELL" as const) : ("BUY" as const),
					deltaPct: Math.abs(drift),
				};
			})
			.filter((t): t is TradeTicket => t !== null)
			.sort((a, b) => b.deltaPct - a.deltaPct);
	});

	const buyCount = $derived(tickets.filter((t) => t.action === "BUY").length);
	const sellCount = $derived(
		tickets.filter((t) => t.action === "SELL").length,
	);
	const totalTurnover = $derived(
		tickets.reduce((s, t) => s + t.deltaPct, 0),
	);

	let executing = $state(false);
	let executed = $state(false);
	let executeError = $state<string | null>(null);

	async function executeAll() {
		executing = true;
		executeError = null;
		try {
			const payload = {
				tickets: tickets.map((t) => ({
					instrument_id: t.instrumentId,
					action: t.action,
					delta_weight: t.deltaPct,
				})),
			};
			await apiPost(
				`/model-portfolios/${portfolioId}/execute-trades`,
				payload,
			);
			executed = true;
			// Re-fetch actual holdings → drift table re-renders with
			// zeroed drifts. This is the crucial feedback cycle.
			await onTradesExecuted();
			// Auto-reset the success state after 4s
			setTimeout(() => {
				executed = false;
			}, 4000);
		} catch (err) {
			executeError =
				err instanceof Error ? err.message : "Trade execution failed";
			// Re-enable the button so the PM can retry
		} finally {
			executing = false;
		}
	}
</script>

<aside class="rsp-root" aria-label="Rebalance suggestions">
	<!-- Print-only institutional header — visible only on paper -->
	<div class="rsp-print-header">
		<div class="rsp-print-logo">InvestIntell</div>
		<h1 class="rsp-print-title">Trade Sheet</h1>
		<div class="rsp-print-meta">
			<span>Portfolio: <strong>{portfolioName}</strong></span>
			<span>Date: {printDate}</span>
			<span>Tickets: {tickets.length} ({buyCount} buy, {sellCount} sell)</span>
			<span>Est. Turnover: {formatPercent(totalTurnover, 2)}</span>
		</div>
		<hr class="rsp-print-rule" />
	</div>

	<header class="rsp-header">
		<h2 class="rsp-title">Trade Suggestions</h2>
		<span class="rsp-subtitle">
			{#if loading}
				Loading...
			{:else}
				{tickets.length} trades &middot; {buyCount} buy &middot; {sellCount} sell
			{/if}
		</span>
	</header>

	<div class="rsp-summary">
		<div class="rsp-stat">
			<span class="rsp-stat-label">Est. Turnover</span>
			<span class="rsp-stat-value">{formatPercent(totalTurnover, 2)}</span>
		</div>
	</div>

	<div class="rsp-tickets">
		{#if loading}
			<div class="rsp-loading">Loading drift data...</div>
		{:else}
			{#each tickets as ticket (ticket.instrumentId)}
				<div class="rsp-ticket" data-action={ticket.action}>
					<div class="rsp-ticket-header">
						<span
							class="rsp-action-chip"
							data-action={ticket.action}
						>
							{ticket.action}
						</span>
						<span class="rsp-ticket-pct">
							{formatPercent(ticket.deltaPct, 2)}
						</span>
					</div>
					<div class="rsp-ticket-name" title={ticket.fundName}>
						{ticket.fundName}
					</div>
					<div class="rsp-ticket-block">
						{blockLabel(ticket.blockId)}
					</div>
				</div>
			{:else}
				<div class="rsp-empty">
					No drift detected. Portfolio is balanced.
				</div>
			{/each}
		{/if}
	</div>

	<footer class="rsp-footer">
		{#if executeError}
			<div class="rsp-error">{executeError}</div>
		{/if}
		{#if executed}
			<div class="rsp-success">
				Trades submitted successfully
			</div>
		{:else}
			<button
				type="button"
				class="rsp-execute"
				disabled={tickets.length === 0 || executing || loading}
				onclick={executeAll}
			>
				{#if executing}
					Executing...
				{:else}
					Approve & Execute Trades
				{/if}
			</button>
		{/if}
		<button
			type="button"
			class="rsp-print"
			disabled={tickets.length === 0 || loading}
			onclick={printTradeSheet}
			title="Print trade sheet for compliance / manual transmission"
			aria-label="Print trade sheet"
		>
			<svg class="rsp-print-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
				<polyline points="6 9 6 2 18 2 18 9"></polyline>
				<path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"></path>
				<rect x="6" y="14" width="12" height="8"></rect>
			</svg>
			Print Trade Sheet
		</button>
	</footer>
</aside>

<style>
	.rsp-root {
		display: flex;
		flex-direction: column;
		height: 100%;
		min-height: 0;
		font-family: "Urbanist", system-ui, sans-serif;
	}

	.rsp-header {
		padding: 12px 14px 10px;
		border-bottom: 1px solid rgba(255, 255, 255, 0.06);
		flex-shrink: 0;
	}
	.rsp-title {
		margin: 0;
		font-size: 13px;
		font-weight: 700;
		color: var(--ii-text-primary, #ffffff);
	}
	.rsp-subtitle {
		font-size: 10px;
		color: var(--ii-text-muted, #85a0bd);
		letter-spacing: 0.02em;
	}

	.rsp-summary {
		padding: 10px 14px;
		border-bottom: 1px solid rgba(255, 255, 255, 0.06);
		flex-shrink: 0;
	}
	.rsp-stat {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}
	.rsp-stat-label {
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--ii-text-muted, #85a0bd);
	}
	.rsp-stat-value {
		font-size: 14px;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-primary, #ffffff);
	}

	.rsp-tickets {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		padding: 8px 10px;
		display: flex;
		flex-direction: column;
		gap: 6px;
	}

	.rsp-loading {
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 32px 12px;
		font-size: 12px;
		color: var(--ii-text-muted, #85a0bd);
	}

	.rsp-ticket {
		padding: 8px 10px;
		background: rgba(255, 255, 255, 0.02);
		border: 1px solid rgba(255, 255, 255, 0.06);
		border-radius: 3px;
	}
	.rsp-ticket[data-action="SELL"] {
		border-left: 2px solid var(--ii-danger, #fc1a1a);
	}
	.rsp-ticket[data-action="BUY"] {
		border-left: 2px solid var(--ii-success, #22c55e);
	}

	.rsp-ticket-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
		margin-bottom: 4px;
	}
	.rsp-action-chip {
		font-size: 9px;
		font-weight: 800;
		letter-spacing: 0.08em;
		padding: 2px 6px;
		border-radius: 2px;
	}
	.rsp-action-chip[data-action="BUY"] {
		background: rgba(34, 197, 94, 0.15);
		color: #22c55e;
	}
	.rsp-action-chip[data-action="SELL"] {
		background: rgba(252, 26, 26, 0.15);
		color: #fc1a1a;
	}
	.rsp-ticket-pct {
		font-size: 12px;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-primary, #ffffff);
	}
	.rsp-ticket-name {
		font-size: 11px;
		color: var(--ii-text-primary, #ffffff);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.rsp-ticket-block {
		font-size: 9px;
		color: var(--ii-text-muted, #85a0bd);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		margin-top: 2px;
	}

	.rsp-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 32px 12px;
		font-size: 12px;
		color: var(--ii-text-muted, #85a0bd);
		font-style: italic;
	}

	.rsp-footer {
		padding: 12px 14px;
		border-top: 1px solid rgba(255, 255, 255, 0.1);
		flex-shrink: 0;
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.rsp-execute {
		appearance: none;
		display: block;
		width: 100%;
		padding: 12px 16px;
		font-family: inherit;
		font-size: 13px;
		font-weight: 700;
		letter-spacing: 0.02em;
		color: #ffffff;
		background: #2d7ef7;
		border: none;
		border-radius: 4px;
		cursor: pointer;
		transition: background-color 120ms ease, opacity 120ms ease;
	}
	.rsp-execute:hover:not(:disabled) {
		background: #1b6de5;
	}
	.rsp-execute:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
	.rsp-execute:focus-visible {
		outline: 2px solid #2d7ef7;
		outline-offset: 2px;
	}
	.rsp-success {
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 12px;
		background: rgba(34, 197, 94, 0.12);
		border: 1px solid rgba(34, 197, 94, 0.3);
		border-radius: 4px;
		font-size: 12px;
		font-weight: 700;
		color: #22c55e;
	}
	.rsp-error {
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 10px;
		background: rgba(252, 26, 26, 0.1);
		border: 1px solid rgba(252, 26, 26, 0.3);
		border-radius: 4px;
		font-size: 11px;
		font-weight: 600;
		color: #fc1a1a;
	}

	.rsp-print {
		appearance: none;
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 6px;
		width: 100%;
		padding: 8px 16px;
		font-family: inherit;
		font-size: 11px;
		font-weight: 600;
		letter-spacing: 0.02em;
		color: var(--ii-text-muted, #85a0bd);
		background: transparent;
		border: 1px solid rgba(255, 255, 255, 0.12);
		border-radius: 4px;
		cursor: pointer;
		transition: color 120ms ease, border-color 120ms ease;
	}
	.rsp-print:hover:not(:disabled) {
		color: #ffffff;
		border-color: rgba(255, 255, 255, 0.3);
	}
	.rsp-print:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}
	.rsp-print:focus-visible {
		outline: 2px solid #2d7ef7;
		outline-offset: 2px;
	}
	.rsp-print-icon {
		flex-shrink: 0;
	}

	/* ── Print-only institutional header ─────────────────────── */
	.rsp-print-header {
		display: none; /* hidden on screen */
	}

	/* ── @media print — component-scoped print rules ─────────
	   The shell handles hiding sidebar/chart/header. This block
	   handles the panel's own print formatting. */
	@media print {
		.rsp-print-header {
			display: block;
			padding: 0 0 12px;
		}
		.rsp-print-logo {
			font-size: 10px;
			font-weight: 700;
			letter-spacing: 0.1em;
			text-transform: uppercase;
			color: #666;
			margin-bottom: 4px;
		}
		.rsp-print-title {
			font-size: 20px;
			font-weight: 700;
			color: #000;
			margin: 0 0 8px;
		}
		.rsp-print-meta {
			display: flex;
			flex-wrap: wrap;
			gap: 4px 20px;
			font-size: 11px;
			color: #333;
		}
		.rsp-print-meta strong {
			font-weight: 700;
		}
		.rsp-print-rule {
			border: none;
			border-top: 2px solid #000;
			margin: 12px 0 0;
		}

		/* Panel itself — white on paper */
		.rsp-root {
			background: #fff !important;
			color: #000 !important;
			border: none !important;
			height: auto !important;
			overflow: visible !important;
		}
		.rsp-header,
		.rsp-summary {
			border-color: #ddd !important;
		}
		.rsp-title {
			color: #000 !important;
		}
		.rsp-subtitle,
		.rsp-stat-label {
			color: #666 !important;
		}
		.rsp-stat-value {
			color: #000 !important;
		}
		.rsp-tickets {
			overflow: visible !important;
			max-height: none !important;
		}
		.rsp-ticket {
			background: #fff !important;
			border: 1px solid #ccc !important;
			break-inside: avoid;
		}
		.rsp-ticket[data-action="SELL"] {
			border-left: 3px solid #c00 !important;
		}
		.rsp-ticket[data-action="BUY"] {
			border-left: 3px solid #060 !important;
		}
		.rsp-action-chip[data-action="BUY"] {
			background: #e6f4ea !important;
			color: #060 !important;
		}
		.rsp-action-chip[data-action="SELL"] {
			background: #fce8e8 !important;
			color: #c00 !important;
		}
		.rsp-ticket-pct,
		.rsp-ticket-name {
			color: #000 !important;
		}
		.rsp-ticket-block {
			color: #666 !important;
		}
		/* Hide interactive elements on paper */
		.rsp-footer {
			display: none !important;
		}
	}
</style>
