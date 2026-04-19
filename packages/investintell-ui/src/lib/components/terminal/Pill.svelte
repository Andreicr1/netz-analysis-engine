<script lang="ts">
	/**
	 * Terminal Pill — small tokenized badge or segmented-control button.
	 * Source: docs/plans/2026-04-18-netz-terminal-parity.md §B.3.
	 */
	export type PillTone = "neutral" | "accent" | "success" | "warn" | "error";
	export type PillSize = "xs" | "sm";
	export type PillAs = "button" | "span";

	interface Props {
		label: string;
		tone?: PillTone;
		size?: PillSize;
		as?: PillAs;
		pressed?: boolean;
		disabled?: boolean;
		ariaLabel?: string;
		onclick?: () => void;
		class?: string;
	}

	let {
		label,
		tone = "neutral",
		size = "sm",
		as = "span",
		pressed,
		disabled = false,
		ariaLabel,
		onclick,
		class: className,
	}: Props = $props();
</script>

{#if as === "button"}
	<button
		type="button"
		class="terminal-pill terminal-pill--{tone} terminal-pill--{size} {className ?? ''}"
		aria-pressed={pressed}
		aria-label={ariaLabel}
		{disabled}
		onclick={() => onclick?.()}
	>
		{label}
	</button>
{:else}
	<span
		class="terminal-pill terminal-pill--{tone} terminal-pill--{size} {className ?? ''}"
		aria-label={ariaLabel}
	>
		{label}
	</span>
{/if}

<style>
	.terminal-pill {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		font-family: var(--terminal-font-mono);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		border-radius: var(--terminal-radius-none);
		border: var(--terminal-border-hairline);
		background: var(--terminal-bg-panel-raised);
		color: var(--terminal-fg-secondary);
		line-height: 1;
		white-space: nowrap;
		transition: color var(--terminal-motion-tick) var(--terminal-motion-easing-out),
			border-color var(--terminal-motion-tick) var(--terminal-motion-easing-out),
			background var(--terminal-motion-tick) var(--terminal-motion-easing-out);
	}

	.terminal-pill--xs {
		font-size: var(--terminal-text-10);
		padding: var(--terminal-space-1) var(--terminal-space-2);
		height: 16px;
	}
	.terminal-pill--sm {
		font-size: var(--terminal-text-11);
		padding: var(--terminal-space-1) var(--terminal-space-3);
		height: 20px;
	}

	.terminal-pill--accent {
		color: var(--terminal-accent-amber);
		border-color: var(--terminal-accent-amber-dim);
	}
	.terminal-pill--success {
		color: var(--terminal-status-success);
		border-color: var(--terminal-status-success);
	}
	.terminal-pill--warn {
		color: var(--terminal-status-warn);
		border-color: var(--terminal-status-warn);
	}
	.terminal-pill--error {
		color: var(--terminal-status-error);
		border-color: var(--terminal-status-error);
	}

	button.terminal-pill {
		cursor: pointer;
	}
	button.terminal-pill:hover:not(:disabled) {
		color: var(--terminal-fg-primary);
		border-color: var(--terminal-fg-secondary);
	}
	button.terminal-pill[aria-pressed="true"] {
		color: var(--terminal-accent-amber);
		border-color: var(--terminal-accent-amber);
		background: var(--terminal-bg-panel-sunken);
	}
	button.terminal-pill:disabled {
		color: var(--terminal-fg-disabled);
		border-color: var(--terminal-fg-disabled);
		cursor: not-allowed;
	}
	button.terminal-pill:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 1px;
	}
</style>
