<script lang="ts">
	interface Props {
		active?: boolean;
	}

	let { active = false }: Props = $props();
</script>

<div class="mnf-root" class:mnf-root--active={active}>
	<div class="mnf-header">
		<span class="mnf-title">MACRO NEWS</span>
		<span class="mnf-badge">LIVE</span>
	</div>
	<div class="mnf-empty">
		<span class="mnf-empty-icon">○</span>
		<span class="mnf-empty-text">News feed not configured</span>
		<span class="mnf-empty-sub">Requires news data provider</span>
	</div>
</div>

<style>
	.mnf-root {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-2);
		min-height: 120px;
		background: var(--terminal-bg-panel);
		border: var(--terminal-border-hairline);
		font-family: var(--terminal-font-mono);
	}
	.mnf-header {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-2);
		padding: var(--terminal-space-2) var(--terminal-space-3) 0;
	}
	.mnf-title {
		color: var(--terminal-fg-primary);
		font-size: var(--terminal-text-11);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
	}
	.mnf-badge {
		padding: 0 3px;
		border: 1px solid var(--terminal-fg-disabled);
		color: var(--terminal-fg-disabled);
		font-size: 9px;
		font-weight: 600;
		letter-spacing: 0.1em;
	}
	.mnf-root--active .mnf-badge {
		border-color: var(--terminal-accent-green, #4adf86);
		color: var(--terminal-accent-green, #4adf86);
	}
	.mnf-empty {
		display: flex;
		flex: 1;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: var(--terminal-space-2);
		padding: var(--terminal-space-3);
	}
	.mnf-empty-icon {
		color: var(--terminal-fg-disabled);
		font-size: 20px;
	}
	.mnf-empty-text {
		color: var(--terminal-fg-secondary);
		font-size: var(--terminal-text-11);
		letter-spacing: var(--terminal-tracking-caps);
	}
	.mnf-empty-sub {
		color: var(--terminal-fg-tertiary);
		font-size: var(--terminal-text-10);
	}
</style>
