<script lang="ts">
	/**
	 * Terminal KpiCard — label + pre-formatted value + optional delta.
	 * Values MUST be pre-formatted by callers using @investintell/ui
	 * formatters (formatCompactCurrency, formatMonoPercent, etc.).
	 * Source: docs/plans/2026-04-18-netz-terminal-parity.md §B.3.
	 */
	export type KpiCardSize = "sm" | "md" | "lg";
	export type KpiDeltaTone = "up" | "down" | "neutral";

	interface Props {
		label: string;
		value: string;
		delta?: string;
		deltaTone?: KpiDeltaTone;
		size?: KpiCardSize;
		mono?: boolean;
		loading?: boolean;
		class?: string;
	}

	let {
		label,
		value,
		delta,
		deltaTone = "neutral",
		size = "md",
		mono = true,
		loading = false,
		class: className,
	}: Props = $props();
</script>

<div
	class="terminal-kpi terminal-kpi--{size} {className ?? ''}"
	data-loading={loading ? "" : undefined}
	data-mono={mono ? "" : undefined}
>
	<div class="terminal-kpi__label">{label}</div>
	<div class="terminal-kpi__value" aria-busy={loading}>
		{#if loading}
			<span class="terminal-kpi__skeleton" aria-hidden="true"></span>
		{:else}
			{value}
		{/if}
	</div>
	{#if delta && !loading}
		<div class="terminal-kpi__delta terminal-kpi__delta--{deltaTone}">{delta}</div>
	{/if}
</div>

<style>
	.terminal-kpi {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-1);
		padding: var(--terminal-space-3);
		background: var(--terminal-bg-panel);
		border: var(--terminal-border-hairline);
		border-radius: var(--terminal-radius-none);
		min-width: 0;
	}

	.terminal-kpi[data-mono] {
		font-family: var(--terminal-font-mono);
	}

	.terminal-kpi__label {
		font-size: var(--t-size-label);
		color: var(--terminal-fg-tertiary);
		text-transform: uppercase;
		letter-spacing: var(--terminal-tracking-caps);
		line-height: var(--terminal-leading-tight);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.terminal-kpi__value {
		color: var(--terminal-fg-primary);
		font-variant-numeric: tabular-nums;
		font-weight: 500;
		line-height: var(--terminal-leading-tight);
		letter-spacing: var(--terminal-tracking-tight);
	}

	.terminal-kpi--sm .terminal-kpi__value {
		font-size: var(--terminal-text-14);
	}
	.terminal-kpi--md .terminal-kpi__value {
		font-size: var(--t-size-kpi);
	}
	.terminal-kpi--lg .terminal-kpi__value {
		font-size: var(--t-size-hero);
	}

	.terminal-kpi__delta {
		font-size: var(--terminal-text-11);
		font-variant-numeric: tabular-nums;
		line-height: 1;
	}
	.terminal-kpi__delta--up {
		color: var(--up);
	}
	.terminal-kpi__delta--down {
		color: var(--down);
	}
	.terminal-kpi__delta--neutral {
		color: var(--terminal-fg-tertiary);
	}

	.terminal-kpi__skeleton {
		display: inline-block;
		width: 4ch;
		height: 1em;
		background: var(--terminal-bg-panel-sunken);
		animation: terminal-kpi-pulse var(--terminal-motion-update) var(--terminal-motion-easing-out) infinite alternate;
	}

	@keyframes terminal-kpi-pulse {
		from {
			opacity: 0.4;
		}
		to {
			opacity: 0.8;
		}
	}
</style>
