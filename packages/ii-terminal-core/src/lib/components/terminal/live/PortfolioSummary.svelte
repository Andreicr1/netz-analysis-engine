<!--
  PortfolioSummary -- vertical KPI panel to the left of Holdings.

  Shows: status badge, AUM, return (1Y), drift status,
  instrument count, last rebalance date, rebalance button.
-->
<script lang="ts">
	import { formatAUM, formatPercent, formatDate } from "@investintell/ui";
	import LiveDot from "$wealth/components/terminal/data/LiveDot.svelte";

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
		<div class="ps-row">
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

		<div class="ps-row">
			<span class="ps-key">AUM</span>
			<span class="ps-val">{formatAUM(aum)}</span>
		</div>

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

		<div class="ps-row">
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

		<div class="ps-row">
			<span class="ps-key">INSTRUMENTS</span>
			<span class="ps-val">{instrumentCount}</span>
		</div>

		<div class="ps-row">
			<span class="ps-key">LAST REBALANCE</span>
			<span class="ps-val">{lastRebalance ? formatDate(lastRebalance, "short") : "\u2014"}</span>
		</div>
	</div>

	{#if driftStatus !== "aligned"}
		<div class="ps-footer">
			<button type="button" class="ps-rebalance-btn" onclick={handleRebalance}>
				REBALANCE
			</button>
		</div>
	{/if}
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
		font-family: var(--terminal-font-mono), "JetBrains Mono", "SF Mono", monospace;
		border-right: var(--terminal-border-hairline);
	}

	.ps-header {
		display: flex;
		align-items: center;
		flex-shrink: 0;
		height: 24px;
		padding: 0 var(--terminal-space-2);
		border-bottom: var(--terminal-border-hairline);
	}

	.ps-label {
		font-family: var(--terminal-font-mono), "JetBrains Mono", "SF Mono", monospace;
		font-size: var(--terminal-text-9);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-tertiary);
		text-transform: uppercase;
	}

	.ps-body {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		padding: var(--terminal-space-2);
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-1);
	}

	.ps-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	.ps-key {
		font-family: var(--terminal-font-mono), "JetBrains Mono", "SF Mono", monospace;
		font-size: var(--terminal-text-9);
		color: var(--terminal-fg-tertiary);
		letter-spacing: var(--terminal-tracking-caps);
	}

	.ps-val {
		font-family: var(--terminal-font-mono), "JetBrains Mono", "SF Mono", monospace;
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

	.ps-up { color: var(--terminal-status-success); }
	.ps-down { color: var(--terminal-status-error); }
	.ps-drift-aligned { color: var(--terminal-status-success); }
	.ps-drift-watch { color: var(--terminal-status-warn); }
	.ps-drift-breach { color: var(--terminal-status-error); }

	.ps-footer {
		flex-shrink: 0;
		padding: var(--terminal-space-1) var(--terminal-space-2);
		border-top: var(--terminal-border-hairline);
	}

	.ps-rebalance-btn {
		width: 100%;
		height: 24px;
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
	}

	.ps-rebalance-btn:hover { opacity: 0.9; }

	.ps-rebalance-btn:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 2px;
	}
</style>
