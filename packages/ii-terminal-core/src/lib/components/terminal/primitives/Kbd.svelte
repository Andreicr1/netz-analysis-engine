<script lang="ts">
	/**
	 * Terminal Kbd — renders a shortcut as tokenized key caps.
	 * Example: keys={["Shift","T"]} → [Shift]+[T].
	 * Source: docs/plans/2026-04-18-netz-terminal-parity.md §B.3.
	 */
	interface Props {
		keys: string[];
		class?: string;
	}

	let { keys, class: className }: Props = $props();
</script>

<span class="terminal-kbd-group {className ?? ''}" role="group">
	{#each keys as key, i (i)}
		{#if i > 0}
			<span class="terminal-kbd-sep" aria-hidden="true">+</span>
		{/if}
		<kbd class="terminal-kbd">{key}</kbd>
	{/each}
</span>

<style>
	.terminal-kbd-group {
		display: inline-flex;
		align-items: center;
		gap: var(--terminal-space-1);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
	}

	.terminal-kbd {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 16px;
		height: 16px;
		padding: 0 var(--terminal-space-1);
		font-family: inherit;
		font-size: inherit;
		text-transform: uppercase;
		color: var(--terminal-fg-secondary);
		background: var(--terminal-bg-panel-sunken);
		border: var(--terminal-border-hairline);
		border-radius: var(--terminal-radius-none);
		line-height: 1;
	}

	.terminal-kbd-sep {
		color: var(--terminal-fg-tertiary);
		font-size: var(--terminal-text-10);
	}
</style>
