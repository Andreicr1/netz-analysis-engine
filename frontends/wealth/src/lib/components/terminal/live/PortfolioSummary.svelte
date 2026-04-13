<!--
  PortfolioSummary -- compact horizontal KPI strip between chart and holdings.

  Single-row layout: STATUS | AUM | RETURN | DRIFT | INSTRUMENTS | REBALANCE
  Height: 32px. Terminal-native styling.
-->
<script lang="ts">
	import { formatAUM, formatPercent } from "@investintell/ui";
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

<div class="ps-strip">
	<!-- Status -->
	<div class="ps-cell">
		<span class="ps-key">STATUS</span>
		<span class="ps-val ps-status">
			<LiveDot
				status={isLive ? "success" : isPaused ? "warn" : "muted"}
				pulse={isLive}
				label="Portfolio state"
			/>
			{isLive ? "LIVE" : isPaused ? "PAUSED" : state.toUpperCase()}
		</span>
	</div>

	<span class="ps-sep" aria-hidden="true"></span>

	<!-- AUM -->
	<div class="ps-cell">
		<span class="ps-key">AUM</span>
		<span class="ps-val">{formatAUM(aum)}</span>
	</div>

	<span class="ps-sep" aria-hidden="true"></span>

	<!-- Return -->
	<div class="ps-cell">
		<span class="ps-key">RETURN</span>
		<span
			class="ps-val"
			class:ps-up={returnPct != null && returnPct >= 0}
			class:ps-down={returnPct != null && returnPct < 0}
		>
			{returnPct != null ? formatPercent(returnPct, 1, "en-US", true) : "\u2014"}
		</span>
	</div>

	<span class="ps-sep" aria-hidden="true"></span>

	<!-- Drift -->
	<div class="ps-cell">
		<span class="ps-key">DRIFT</span>
		<span
			class="ps-val"
			class:ps-drift-aligned={driftStatus === "aligned"}
			class:ps-drift-watch={driftStatus === "watch"}
			class:ps-drift-breach={driftStatus === "breach"}
		>
			{driftLabel}
		</span>
	</div>

	<span class="ps-sep" aria-hidden="true"></span>

	<!-- Instruments -->
	<div class="ps-cell">
		<span class="ps-key">INSTRUMENTS</span>
		<span class="ps-val">{instrumentCount}</span>
	</div>

	<!-- Spacer pushes rebalance to far right -->
	<div class="ps-spacer"></div>

	<!-- Rebalance button (only when drift is not aligned) -->
	{#if driftStatus !== "aligned"}
		<button type="button" class="ps-rebalance-btn" onclick={handleRebalance}>
			REBALANCE
		</button>
	{/if}
</div>

<style>
	.ps-strip {
		display: flex;
		align-items: center;
		height: 32px;
		padding: 0 var(--terminal-space-2);
		gap: var(--terminal-space-3);
		background: var(--terminal-bg-panel);
		font-family: var(--terminal-font-mono);
		border-top: var(--terminal-border-hairline);
		border-bottom: var(--terminal-border-hairline);
		flex-shrink: 0;
	}

	.ps-cell {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-1);
		white-space: nowrap;
	}

	.ps-key {
		font-size: var(--terminal-text-9);
		color: var(--terminal-fg-tertiary);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}

	.ps-val {
		font-size: var(--terminal-text-10);
		font-weight: 600;
		color: var(--terminal-fg-primary);
		font-variant-numeric: tabular-nums;
	}

	.ps-status {
		display: flex;
		align-items: center;
		gap: 4px;
	}

	.ps-sep {
		width: 1px;
		height: 14px;
		background: var(--terminal-fg-muted);
		flex-shrink: 0;
	}

	.ps-spacer {
		flex: 1;
	}

	.ps-up {
		color: var(--terminal-status-success);
	}

	.ps-down {
		color: var(--terminal-status-error);
	}

	.ps-drift-aligned {
		color: var(--terminal-status-success);
	}

	.ps-drift-watch {
		color: var(--terminal-status-warn);
	}

	.ps-drift-breach {
		color: var(--terminal-status-error);
	}

	.ps-rebalance-btn {
		height: 22px;
		padding: 0 var(--terminal-space-2);
		background: var(--terminal-accent-amber);
		color: var(--terminal-bg-void);
		border: none;
		border-radius: var(--terminal-radius-none);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-9);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		cursor: pointer;
		flex-shrink: 0;
	}

	.ps-rebalance-btn:hover {
		opacity: 0.9;
	}

	.ps-rebalance-btn:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 2px;
	}
</style>
