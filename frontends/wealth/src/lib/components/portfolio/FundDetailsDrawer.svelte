<!--
  FundDetailsDrawer — Slide-out panel showing the full metric set
  for a universe fund. Opens from the right edge when the PM clicks
  a fund row in the Universe table. Closes via X button or Escape.

  Shows the 8 KPI fields removed from the lean Universe table:
  AUM, 3Y Return, Risk-Adjusted Return, Max Drawdown, Correlation
  to Portfolio, Momentum, Liquidity, and Score — plus Ticker
  and Asset Class for context.

  Phase 11 "Million Dollar" refactor — dedicated viewer pattern.
-->
<script lang="ts">
	import X from "lucide-svelte/icons/x";
	import TrendingUp from "lucide-svelte/icons/trending-up";
	import TrendingDown from "lucide-svelte/icons/trending-down";
	import Minus from "lucide-svelte/icons/minus";
	import { formatPercent, formatAUM, formatNumber } from "@investintell/ui";
	import type { UniverseFund } from "$wealth/state/portfolio-workspace.svelte";

	interface Props {
		fund: UniverseFund;
		onClose: () => void;
	}

	let { fund, onClose }: Props = $props();

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === "Escape") {
			e.preventDefault();
			onClose();
		}
	}

	function handleBackdropClick() {
		onClose();
	}

	function handlePanelClick(e: MouseEvent) {
		e.stopPropagation();
	}

	// ── Formatters ────────────────────────────────────────────
	function fmt(value: number | null | undefined, type: "pct" | "pct_signed" | "ratio" | "aum" | "score"): string {
		if (value == null) return "—";
		switch (type) {
			case "pct": return formatPercent(value, 2);
			case "pct_signed": {
				const s = formatPercent(value, 2);
				return value > 0 ? `+${s}` : s;
			}
			case "ratio": return formatNumber(value, 2);
			case "aum": return formatAUM(value);
			case "score": return formatNumber(value, 0);
		}
	}

	function momentumLabel(value: number | null | undefined): { text: string; color: string; Icon: typeof TrendingUp } {
		if (value == null) return { text: "No data", color: "#85a0bd", Icon: Minus };
		if (value > 0.15) return { text: "Positive", color: "#16a34a", Icon: TrendingUp };
		if (value < -0.15) return { text: "Negative", color: "#dc2626", Icon: TrendingDown };
		return { text: "Neutral", color: "#85a0bd", Icon: Minus };
	}

	function corrColor(value: number | null | undefined): string {
		if (value == null) return "#85a0bd";
		if (value <= -0.3) return "#16a34a";
		if (value <= 0.3) return "#cbccd1";
		if (value <= 0.7) return "#f59e0b";
		return "#dc2626";
	}

	const mom = $derived(momentumLabel(fund.blended_momentum_score ?? null));
	const MomIcon = $derived(mom.Icon);
</script>

<svelte:window onkeydown={handleKeydown} />

<!-- Backdrop + Panel -->
<div
	class="fdd-backdrop"
	onclick={handleBackdropClick}
	onkeydown={handleKeydown}
	role="presentation"
>
	<div
		class="fdd-panel"
		onclick={handlePanelClick}
		onkeydown={handleKeydown}
		role="dialog"
		aria-label="Fund details: {fund.fund_name}"
		aria-modal="true"
		tabindex="-1"
	>
		<!-- Header -->
		<header class="fdd-header">
			<div class="fdd-header-text">
				<h2 class="fdd-name">{fund.fund_name}</h2>
				<div class="fdd-sub">
					{#if fund.ticker}
						<span class="fdd-ticker">{fund.ticker}</span>
					{/if}
					{#if fund.asset_class}
						<span class="fdd-chip">{fund.asset_class}</span>
					{/if}
				</div>
			</div>
			<button type="button" class="fdd-close" onclick={onClose} aria-label="Close">
				<X size={18} />
			</button>
		</header>

		<!-- KPI Grid -->
		<div class="fdd-body">
			<div class="fdd-grid">
				<div class="fdd-kpi">
					<span class="fdd-kpi-label">AUM</span>
					<span class="fdd-kpi-value">{fmt(fund.aum_usd ?? null, "aum")}</span>
				</div>

				<div class="fdd-kpi">
					<span class="fdd-kpi-label">Expense Ratio</span>
					<span class="fdd-kpi-value">{fmt(fund.expense_ratio ?? null, "pct")}</span>
				</div>

				<div class="fdd-kpi">
					<span class="fdd-kpi-label">3Y Annualized Return</span>
					<span class="fdd-kpi-value">{fmt(fund.return_3y_ann ?? null, "pct_signed")}</span>
				</div>

				<div class="fdd-kpi">
					<span class="fdd-kpi-label">Risk-Adjusted Return</span>
					<span class="fdd-kpi-value">{fmt(fund.sharpe_1y ?? null, "ratio")}</span>
				</div>

				<div class="fdd-kpi">
					<span class="fdd-kpi-label">Maximum Drawdown</span>
					<span class="fdd-kpi-value fdd-kpi-value--loss">{fmt(fund.max_drawdown_1y ?? null, "pct")}</span>
				</div>

				<div class="fdd-kpi">
					<span class="fdd-kpi-label">Correlation to Portfolio</span>
					<span class="fdd-kpi-value" style:color={corrColor(fund.correlation_to_portfolio ?? null)}>
						{fmt(fund.correlation_to_portfolio ?? null, "ratio")}
					</span>
				</div>

				<div class="fdd-kpi">
					<span class="fdd-kpi-label">Momentum</span>
					<span class="fdd-kpi-value fdd-kpi-row" style:color={mom.color}>
						<MomIcon size={14} />
						{mom.text}
					</span>
				</div>

				<div class="fdd-kpi">
					<span class="fdd-kpi-label">Liquidity</span>
					<span class="fdd-kpi-value">
						<span class="fdd-liquidity-pill">{fund.liquidity_tier ?? "—"}</span>
					</span>
				</div>

				<div class="fdd-kpi fdd-kpi--accent">
					<span class="fdd-kpi-label">Score</span>
					<span class="fdd-kpi-value fdd-kpi-value--score">{fmt(fund.manager_score ?? null, "score")}</span>
				</div>
			</div>

			<!-- Context row -->
			<div class="fdd-context">
				<div class="fdd-context-row">
					<span class="fdd-context-label">Block</span>
					<span class="fdd-context-value">{fund.block_label}</span>
				</div>
				{#if fund.geography}
					<div class="fdd-context-row">
						<span class="fdd-context-label">Geography</span>
						<span class="fdd-context-value">{fund.geography}</span>
					</div>
				{/if}
				<div class="fdd-context-row">
					<span class="fdd-context-label">Type</span>
					<span class="fdd-context-value">{fund.instrument_type}</span>
				</div>
			</div>
		</div>
	</div>
</div>

<style>
	/* ── Backdrop ────────────────────────────────────────────── */
	.fdd-backdrop {
		position: fixed;
		inset: 0;
		z-index: 50;
		background: rgba(0, 0, 0, 0.5);
		backdrop-filter: blur(2px);
	}

	/* ── Panel ───────────────────────────────────────────────── */
	.fdd-panel {
		position: fixed;
		top: 0;
		right: 0;
		height: 100vh;
		width: 400px;
		max-width: 90vw;
		background: #0a0e17;
		border-left: 1px solid rgba(64, 66, 73, 0.5);
		box-shadow: -12px 0 40px -8px rgba(0, 0, 0, 0.6);
		display: flex;
		flex-direction: column;
		overflow: hidden;
		animation: fdd-slide-in 200ms ease-out;
	}

	@keyframes fdd-slide-in {
		from { transform: translateX(100%); }
		to { transform: translateX(0); }
	}

	/* ── Header ──────────────────────────────────────────────── */
	.fdd-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 12px;
		padding: 20px 20px 16px;
		border-bottom: 1px solid rgba(64, 66, 73, 0.4);
		flex-shrink: 0;
	}

	.fdd-header-text {
		display: flex;
		flex-direction: column;
		gap: 8px;
		min-width: 0;
	}

	.fdd-name {
		margin: 0;
		font-size: 16px;
		font-weight: 700;
		color: #ffffff;
		font-family: "Urbanist", sans-serif;
		line-height: 1.3;
	}

	.fdd-sub {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.fdd-ticker {
		font-size: 12px;
		font-weight: 600;
		color: #0177fb;
		font-variant-numeric: tabular-nums;
		font-family: "Urbanist", sans-serif;
	}

	.fdd-chip {
		display: inline-flex;
		align-items: center;
		padding: 2px 8px;
		border-radius: 999px;
		font-size: 11px;
		font-weight: 500;
		background: rgba(255, 255, 255, 0.06);
		color: #cbccd1;
	}

	.fdd-close {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 32px;
		height: 32px;
		border: none;
		border-radius: 6px;
		background: transparent;
		color: #85a0bd;
		cursor: pointer;
		flex-shrink: 0;
		transition: all 120ms ease;
	}
	.fdd-close:hover {
		background: rgba(255, 255, 255, 0.06);
		color: #ffffff;
	}
	.fdd-close:focus-visible {
		outline: 2px solid #2d7ef7;
		outline-offset: 2px;
	}

	/* ── Body ────────────────────────────────────────────────── */
	.fdd-body {
		flex: 1;
		overflow-y: auto;
		padding: 20px;
	}

	/* ── KPI Grid (2 columns) ────────────────────────────────── */
	.fdd-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 2px;
	}

	.fdd-kpi {
		display: flex;
		flex-direction: column;
		gap: 4px;
		padding: 14px 12px;
		background: rgba(255, 255, 255, 0.02);
		border-radius: 4px;
	}

	.fdd-kpi--accent {
		grid-column: 1 / -1;
		background: rgba(1, 119, 251, 0.06);
		border: 1px solid rgba(1, 119, 251, 0.15);
	}

	.fdd-kpi-label {
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: #85a0bd;
		font-family: "Urbanist", sans-serif;
	}

	.fdd-kpi-value {
		font-size: 16px;
		font-weight: 700;
		color: #ffffff;
		font-variant-numeric: tabular-nums;
		font-family: "Urbanist", sans-serif;
	}

	.fdd-kpi-value--loss {
		color: #dc2626;
	}

	.fdd-kpi-value--score {
		font-size: 22px;
		color: #0177fb;
	}

	.fdd-kpi-row {
		display: flex;
		align-items: center;
		gap: 6px;
	}

	.fdd-liquidity-pill {
		display: inline-flex;
		align-items: center;
		padding: 2px 10px;
		border-radius: 999px;
		font-size: 12px;
		font-weight: 500;
		background: rgba(255, 255, 255, 0.05);
		color: #cbccd1;
	}

	/* ── Context section ─────────────────────────────────────── */
	.fdd-context {
		margin-top: 20px;
		padding-top: 16px;
		border-top: 1px solid rgba(64, 66, 73, 0.3);
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.fdd-context-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
	}

	.fdd-context-label {
		font-size: 11px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: #85a0bd;
		font-family: "Urbanist", sans-serif;
	}

	.fdd-context-value {
		font-size: 13px;
		font-weight: 500;
		color: #cbccd1;
		font-family: "Urbanist", sans-serif;
		text-align: right;
	}
</style>
