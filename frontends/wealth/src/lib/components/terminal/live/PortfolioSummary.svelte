<!--
  PortfolioSummary -- aggregate stats panel (bottom-left of right column).

  Shows: status badge, AUM, return (1Y), drift status,
  instrument count, last rebalance date, rebalance button (stub).
-->
<script lang="ts">
	import { formatAUM, formatPercent, formatDate } from "@investintell/ui";
	import LiveDot from "$lib/components/terminal/data/LiveDot.svelte";

	interface Props {
		status: string;
		state: string;
		aum: number;
		returnPct: number | null;
		driftStatus: "aligned" | "watch" | "breach";
		instrumentCount: number;
		lastRebalance: string | null;
		onRebalance?: () => void;
	}

	let {
		status,
		state,
		aum,
		returnPct,
		driftStatus,
		instrumentCount,
		lastRebalance,
		onRebalance,
	}: Props = $props();

	const isLive = $derived(state === "live");
	const isPaused = $derived(state === "paused");

	const driftLabel = $derived.by(() => {
		switch (driftStatus) {
			case "aligned":
				return "Aligned";
			case "watch":
				return "Watch";
			case "breach":
				return "Breach";
			default:
				return "Unknown";
		}
	});

	function handleRebalance() {
		onRebalance?.();
	}
</script>

<div class="ps-root">
	<div class="ps-header">
		<span class="ps-label">PORTFOLIO</span>
	</div>

	<div class="ps-body">
		<!-- Status -->
		<div class="ps-row">
			<span class="ps-key">STATUS</span>
			<span class="ps-val ps-status">
				<LiveDot
					status={isLive ? "success" : isPaused ? "warn" : "muted"}
					pulse={isLive}
					label="Portfolio state: {isLive ? 'live' : isPaused ? 'paused' : state}"
				/>
				{isLive ? "LIVE" : isPaused ? "PAUSED" : state.toUpperCase()}
			</span>
		</div>

		<!-- AUM -->
		<div class="ps-row">
			<span class="ps-key">AUM</span>
			<span class="ps-val">{formatAUM(aum)}</span>
		</div>

		<!-- Return -->
		<div class="ps-row">
			<span class="ps-key">RETURN (1Y)</span>
			<span
				class="ps-val"
				class:ps-up={returnPct != null && returnPct >= 0}
				class:ps-down={returnPct != null && returnPct < 0}
			>
				{returnPct != null ? formatPercent(returnPct, 1, "en-US", true) : "\u2014"}
			</span>
		</div>

		<!-- Drift Status -->
		<div class="ps-row">
			<span class="ps-key">DRIFT STATUS</span>
			<span
				class="ps-val"
				class:ps-drift-aligned={driftStatus === "aligned"}
				class:ps-drift-watch={driftStatus === "watch"}
				class:ps-drift-breach={driftStatus === "breach"}
			>
				{driftLabel}
			</span>
		</div>

		<!-- Instruments -->
		<div class="ps-row">
			<span class="ps-key">INSTRUMENTS</span>
			<span class="ps-val">{instrumentCount}</span>
		</div>

		<!-- Last Rebalance -->
		<div class="ps-row">
			<span class="ps-key">LAST REBALANCE</span>
			<span class="ps-val">{lastRebalance ? formatDate(lastRebalance, "short") : "\u2014"}</span>
		</div>
	</div>

	<div class="ps-footer">
		{#if driftStatus !== "aligned"}
			<button type="button" class="ps-rebalance-btn" onclick={handleRebalance}>
				REBALANCE
			</button>
		{:else}
			<span class="ps-footer-status">Portfolio aligned</span>
		{/if}
	</div>
</div>

<style>
	.ps-root {
		display: flex;
		flex-direction: column;
		width: 100%;
		height: 100%;
		min-height: 0;
		overflow: hidden;
		background: var(--terminal-bg-panel);
		font-family: var(--terminal-font-mono);
	}

	.ps-header {
		display: flex;
		align-items: center;
		flex-shrink: 0;
		height: 28px;
		padding: 0 var(--terminal-space-3);
		border-bottom: var(--terminal-border-hairline);
	}

	.ps-label {
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-tertiary);
		text-transform: uppercase;
	}

	.ps-body {
		flex: 1;
		min-height: 0;
		padding: var(--terminal-space-3);
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-2);
	}

	.ps-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	.ps-key {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		letter-spacing: var(--terminal-tracking-caps);
	}

	.ps-val {
		font-size: var(--terminal-text-11);
		font-weight: 600;
		color: var(--terminal-fg-primary);
		font-variant-numeric: tabular-nums;
	}

	/* Status dot */
	.ps-status {
		display: flex;
		align-items: center;
		gap: 6px;
	}

	/* P&L colors */
	.ps-up {
		color: var(--terminal-status-success);
	}

	.ps-down {
		color: var(--terminal-status-error);
	}

	/* Drift colors */
	.ps-drift-aligned {
		color: var(--terminal-status-success);
	}

	.ps-drift-watch {
		color: var(--terminal-status-warn);
	}

	.ps-drift-breach {
		color: var(--terminal-status-error);
	}

	/* Footer */
	.ps-footer {
		flex-shrink: 0;
		padding: var(--terminal-space-2) var(--terminal-space-3);
		border-top: var(--terminal-border-hairline);
	}

	.ps-rebalance-btn {
		appearance: none;
		width: 100%;
		height: 28px;
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-accent-amber);
		background: transparent;
		border: 1px solid var(--terminal-accent-amber-dim);
		cursor: pointer;
		transition: background var(--terminal-motion-tick), border-color var(--terminal-motion-tick);
	}

	.ps-rebalance-btn:hover {
		background: var(--terminal-bg-panel-raised);
		border-color: var(--terminal-accent-amber);
	}

	.ps-rebalance-btn:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 1px;
	}

	.ps-footer-status {
		font-size: var(--terminal-text-10);
		color: var(--terminal-status-success);
		letter-spacing: var(--terminal-tracking-caps);
		font-weight: 600;
		text-align: center;
		display: block;
	}
</style>
