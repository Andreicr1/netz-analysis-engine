<script lang="ts">
	export type Accent = "amber" | "cyan" | "violet";

	interface Props {
		value: Accent;
		onChange: (v: Accent) => void;
		class?: string;
	}

	let { value, onChange, class: className }: Props = $props();

	const options: { label: string; val: Accent }[] = [
		{ label: "AMBER", val: "amber" },
		{ label: "CYAN", val: "cyan" },
		{ label: "VIOLET", val: "violet" },
	];
</script>

<div class="terminal-accent-picker {className ?? ''}" role="radiogroup" aria-label="Accent">
	{#each options as opt (opt.val)}
		<button
			type="button"
			class="terminal-accent-swatch terminal-accent-swatch--{opt.val}"
			class:is-active={value === opt.val}
			aria-pressed={value === opt.val}
			aria-label={`Accent ${opt.label}`}
			onclick={() => onChange(opt.val)}
		>
			<span class="terminal-accent-dot" aria-hidden="true"></span>
			<span class="terminal-accent-label">{opt.label}</span>
		</button>
	{/each}
</div>

<style>
	.terminal-accent-picker {
		display: inline-flex;
		gap: var(--terminal-space-1);
	}

	.terminal-accent-swatch {
		display: inline-flex;
		align-items: center;
		gap: var(--terminal-space-2);
		padding: var(--terminal-space-1) var(--terminal-space-3);
		height: 20px;
		background: var(--terminal-bg-panel-raised);
		border: var(--terminal-border-hairline);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		color: var(--terminal-fg-secondary);
		cursor: pointer;
		line-height: 1;
	}

	.terminal-accent-swatch:hover {
		color: var(--terminal-fg-primary);
		border-color: var(--terminal-fg-secondary);
	}

	.terminal-accent-swatch.is-active {
		color: var(--terminal-fg-primary);
		background: var(--terminal-bg-panel-sunken);
	}

	.terminal-accent-swatch:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 1px;
	}

	.terminal-accent-dot {
		width: 8px;
		height: 8px;
		display: inline-block;
		border-radius: 50%;
	}
	.terminal-accent-swatch--amber .terminal-accent-dot {
		background: var(--terminal-accent-amber);
	}
	.terminal-accent-swatch--cyan .terminal-accent-dot {
		background: var(--terminal-accent-cyan);
	}
	.terminal-accent-swatch--violet .terminal-accent-dot {
		background: var(--terminal-accent-violet);
	}

	.terminal-accent-swatch.is-active {
		border-color: var(--terminal-accent-amber);
	}
</style>
