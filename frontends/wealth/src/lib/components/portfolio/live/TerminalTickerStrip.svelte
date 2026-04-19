<!--
  TerminalTickerStrip — 44px command center header.

  Layout (flex, left→right):
    [PortfolioDropdown] | TICKER  PRICE  CHG%  BID/ASK | RET  VOL  DRIFT | [EXIT]

  All numeric data uses monospace tabular-nums for alignment.
  Strictly 44px height — never exceeds the grid-template-rows budget.
-->
<script lang="ts">
	import { formatNumber } from "@investintell/ui";
	import PortfolioDropdown from "./PortfolioDropdown.svelte";
	import type { ModelPortfolio } from "$wealth/types/model-portfolio";
	import type { DraftHolding, OverlapResultRead } from "./LiveWorkbenchShell.svelte";

	interface PriceData {
		ticker: string;
		price: number;
		changePct: number;
		bid: number | null;
		ask: number | null;
	}

	interface PortfolioKpis {
		expectedReturn: number | null;
		volatility: number | null;
		driftAlerts: number;
	}

	interface Props {
		portfolios: readonly ModelPortfolio[];
		selected: ModelPortfolio | null;
		onSelect: (portfolio: ModelPortfolio) => void;
		priceData: PriceData;
		kpis: PortfolioKpis;
		mode: "LIVE" | "EDIT";
		draftHoldings: DraftHolding[];
		onEdit: () => void;
		onCancelEdit: () => void;
		onPublish: () => void;
		onExit: () => void;
		overlapResult?: OverlapResultRead | null;
	}

	let {
		portfolios,
		selected,
		onSelect,
		priceData,
		kpis,
		mode,
		draftHoldings,
		onEdit,
		onCancelEdit,
		onPublish,
		onExit,
		overlapResult = null,
	}: Props = $props();

	const draftTotal = $derived(
		draftHoldings.reduce((sum, h) => sum + h.targetWeight, 0),
	);
	const canPublish = $derived(
		draftHoldings.length > 0 && Math.abs(draftTotal - 100) < 0.01,
	);

	const isUp = $derived(priceData.changePct >= 0);
	const hasBreach = $derived((overlapResult?.breaches.length ?? 0) > 0);

	function fmt(n: number | null, decimals = 2): string {
		if (n === null || n === undefined) return "---";
		return formatNumber(n, decimals);
	}

	function fmtPct(n: number | null): string {
		if (n === null || n === undefined) return "---";
		const sign = n >= 0 ? "+" : "";
		return `${sign}${formatNumber(n, 2)}%`;
	}
</script>

<header class="ts-root" aria-label="Terminal ticker strip">
	<!-- LEFT: Portfolio selector -->
	<div class="ts-left">
		<PortfolioDropdown {portfolios} {selected} {onSelect} />
	</div>

	<!-- SEPARATOR -->
	<div class="ts-sep" aria-hidden="true"></div>

	<!-- CENTER-LEFT: Active price (live-updating region) -->
	<div class="ts-price-block" aria-live="polite" aria-atomic="true">
		<span class="ts-ticker">{priceData.ticker}</span>
		<span class="ts-price">{fmt(priceData.price)}</span>
		<span class="ts-change" class:ts-up={isUp} class:ts-down={!isUp}>
			<span class="ts-arrow" aria-hidden="true">{isUp ? "\u25B2" : "\u25BC"}</span>
			{fmtPct(priceData.changePct)}
		</span>
		{#if priceData.bid !== null && priceData.ask !== null}
			<span class="ts-bidask">
				<span class="ts-bidask-label">B</span>{fmt(priceData.bid)}
				<span class="ts-bidask-sep">/</span>
				<span class="ts-bidask-label">A</span>{fmt(priceData.ask)}
			</span>
		{/if}
	</div>

	<!-- SEPARATOR -->
	<div class="ts-sep" aria-hidden="true"></div>

	<!-- CENTER-RIGHT: Portfolio KPIs -->
	<div class="ts-kpis">
		<div class="ts-kpi">
			<span class="ts-kpi-label">Ret</span>
			<span class="ts-kpi-value">{fmtPct(kpis.expectedReturn)}</span>
		</div>
		<div class="ts-kpi">
			<span class="ts-kpi-label">Vol</span>
			<span class="ts-kpi-value">{fmt(kpis.volatility)}%</span>
		</div>
		{#if kpis.driftAlerts > 0}
			<div class="ts-drift-badge" title="{kpis.driftAlerts} drift alert(s)">
				<span class="ts-drift-icon" aria-hidden="true">!</span>
				{kpis.driftAlerts}
			</div>
		{/if}
	</div>

	<!-- MODE ACTIONS -->
	<div class="ts-mode-actions">
		{#if mode === "LIVE"}
			<button
				type="button"
				class="ts-mode-btn ts-mode-btn--edit"
				onclick={onEdit}
				title="Enter edit mode to build a portfolio"
			>Edit Portfolio</button>
		{:else}
			<button
				type="button"
				class="ts-mode-btn ts-mode-btn--cancel"
				onclick={onCancelEdit}
			>Cancel</button>
			<button
				type="button"
				class="ts-mode-btn ts-mode-btn--publish"
				class:ts-mode-btn--warning={hasBreach}
				disabled={!canPublish}
				onclick={onPublish}
			>Publish &amp; Fund</button>
		{/if}
	</div>

	<!-- RIGHT: Exit -->
	<div class="ts-right">
		<button
			type="button"
			class="ts-exit"
			onclick={onExit}
			title="Exit terminal"
			aria-label="Exit terminal"
		>&#x2715;</button>
	</div>
</header>

<style>
	.ts-root {
		display: flex;
		align-items: center;
		gap: 0;
		width: 100%;
		height: 44px;
		padding: 0 12px;
		background: #0c1018;
		border-bottom: 1px solid rgba(255, 255, 255, 0.08);
		font-family: "Urbanist", system-ui, sans-serif;
		/* NO overflow: hidden — the PortfolioDropdown list must
		   extend below the 44px strip into the chart area.
		   Horizontal clipping is handled by flex nowrap + min-width: 0
		   on individual flex children. */
		overflow: visible;
	}

	/* ── Vertical separators ─────────────────────────────── */
	.ts-sep {
		width: 1px;
		height: 24px;
		margin: 0 12px;
		background: rgba(255, 255, 255, 0.08);
		flex-shrink: 0;
	}

	/* ── Left: dropdown ──────────────────────────────────── */
	.ts-left {
		flex-shrink: 0;
		min-width: 0;
	}

	/* ── Center-left: price block ────────────────────────── */
	.ts-price-block {
		display: flex;
		align-items: center;
		gap: 10px;
		flex-shrink: 0;
		font-family: "JetBrains Mono", "SF Mono", "Cascadia Code", monospace;
		font-variant-numeric: tabular-nums;
	}

	.ts-ticker {
		font-size: 11px;
		font-weight: 700;
		letter-spacing: 0.06em;
		color: #c8d0dc;
	}

	.ts-price {
		font-size: 16px;
		font-weight: 700;
		color: #ffffff;
		letter-spacing: -0.01em;
	}

	.ts-change {
		display: inline-flex;
		align-items: center;
		gap: 3px;
		font-size: 11px;
		font-weight: 600;
	}
	.ts-up { color: #22c55e; }
	.ts-down { color: #ef4444; }

	.ts-arrow {
		font-size: 8px;
		line-height: 1;
	}

	.ts-bidask {
		display: inline-flex;
		align-items: center;
		gap: 2px;
		font-size: 10px;
		color: #5a6577;
	}
	.ts-bidask-label {
		font-size: 9px;
		font-weight: 700;
		color: #3d4654;
	}
	.ts-bidask-sep {
		color: #3d4654;
		margin: 0 1px;
	}

	/* ── Center-right: KPIs ──────────────────────────────── */
	.ts-kpis {
		display: flex;
		align-items: center;
		gap: 16px;
		margin-left: auto;
		flex-shrink: 0;
		font-family: "JetBrains Mono", "SF Mono", "Cascadia Code", monospace;
		font-variant-numeric: tabular-nums;
	}

	.ts-kpi {
		display: flex;
		align-items: center;
		gap: 5px;
	}
	.ts-kpi-label {
		font-size: 10px;
		font-weight: 600;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: #5a6577;
	}
	.ts-kpi-value {
		font-size: 11px;
		font-weight: 600;
		color: #c8d0dc;
	}

	/* ── Drift badge ─────────────────────────────────────── */
	.ts-drift-badge {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 2px 7px;
		font-family: "JetBrains Mono", "SF Mono", monospace;
		font-size: 10px;
		font-weight: 700;
		color: #f59e0b;
		background: rgba(245, 158, 11, 0.10);
		border: 1px solid rgba(245, 158, 11, 0.25);
	}
	.ts-drift-icon {
		font-size: 9px;
		font-weight: 800;
	}

	/* ── Right: exit button ──────────────────────────────── */
	.ts-right {
		flex-shrink: 0;
		margin-left: 12px;
	}

	.ts-exit {
		appearance: none;
		display: flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		padding: 0;
		font-size: 13px;
		color: #5a6577;
		background: transparent;
		border: 1px solid rgba(255, 255, 255, 0.08);
		cursor: pointer;
		transition: color 80ms, border-color 80ms, background 80ms;
	}
	.ts-exit:hover {
		color: #ef4444;
		border-color: rgba(239, 68, 68, 0.3);
		background: rgba(239, 68, 68, 0.06);
	}
	.ts-exit:focus-visible {
		outline: 2px solid #2d7ef7;
		outline-offset: 1px;
	}

	/* ── Mode action buttons ────────────────────────────────── */
	.ts-mode-actions {
		display: flex;
		align-items: center;
		gap: 6px;
		margin-left: 12px;
		flex-shrink: 0;
	}

	.ts-mode-btn {
		appearance: none;
		height: 28px;
		padding: 0 12px;
		font-family: inherit;
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.03em;
		border: none;
		cursor: pointer;
		transition: background 80ms, opacity 80ms;
		white-space: nowrap;
	}
	.ts-mode-btn:focus-visible {
		outline: 2px solid #2d7ef7;
		outline-offset: 1px;
	}
	.ts-mode-btn--edit {
		color: #c8d0dc;
		background: rgba(255, 255, 255, 0.06);
		border: 1px solid rgba(255, 255, 255, 0.10);
	}
	.ts-mode-btn--edit:hover {
		background: rgba(255, 255, 255, 0.10);
	}
	.ts-mode-btn--cancel {
		color: #8896a8;
		background: rgba(255, 255, 255, 0.06);
	}
	.ts-mode-btn--cancel:hover {
		background: rgba(255, 255, 255, 0.10);
		color: #c8d0dc;
	}
	.ts-mode-btn--publish {
		color: #ffffff;
		background: #2d7ef7;
		font-size: 11px;
		padding: 0 16px;
	}
	.ts-mode-btn--publish:hover:not(:disabled) {
		background: #3b8bff;
	}
	.ts-mode-btn--publish:disabled {
		opacity: 0.35;
		cursor: not-allowed;
	}
	.ts-mode-btn--warning {
		background: #ca8a04;
		border: 1px solid rgba(202, 138, 4, 0.4);
	}
	.ts-mode-btn--warning:hover:not(:disabled) {
		background: #eab308;
	}
</style>
