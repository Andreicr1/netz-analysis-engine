<!--
  X3.1 — Builder tab strip.

  Top-level tab router for the unified builder workspace:
  [ STRATEGIC | PORTFOLIO | STRESS ]. URL param ?tab={strategic|
  portfolio|stress} drives the active state so direct links, refresh,
  and back-button preserve context.

  Matches the `.bd-tabs` visual from docs/ux/Netz Terminal/builder.css
  (active tab uses amber accent + bottom border).
-->
<script lang="ts">
	export type BuilderTab = "strategic" | "portfolio" | "stress";

	interface Props {
		active: BuilderTab;
		onchange: (tab: BuilderTab) => void;
	}

	let { active, onchange }: Props = $props();

	const TABS: { id: BuilderTab; label: string }[] = [
		{ id: "strategic", label: "Strategic" },
		{ id: "portfolio", label: "Portfolio" },
		{ id: "stress", label: "Stress" },
	];
</script>

<div class="tab-strip" role="tablist" aria-label="Builder workspace tabs">
	{#each TABS as tab (tab.id)}
		{@const isActive = active === tab.id}
		<button
			type="button"
			role="tab"
			aria-selected={isActive}
			class="tab-strip__btn"
			class:tab-strip__btn--active={isActive}
			onclick={() => onchange(tab.id)}
		>
			{tab.label}
		</button>
	{/each}
</div>

<style>
	.tab-strip {
		display: flex;
		align-items: stretch;
		height: 32px;
		border-bottom: var(--terminal-border-hairline);
		background: var(--terminal-bg-void);
		flex-shrink: 0;
	}

	.tab-strip__btn {
		display: inline-flex;
		align-items: center;
		padding: 0 var(--terminal-space-4);
		background: transparent;
		border: none;
		border-right: var(--terminal-border-hairline);
		border-bottom: 2px solid transparent;
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		color: var(--terminal-fg-tertiary);
		cursor: pointer;
		transition:
			color var(--terminal-motion-tick) var(--terminal-motion-easing-out),
			border-color var(--terminal-motion-tick) var(--terminal-motion-easing-out);
	}
	.tab-strip__btn:hover {
		color: var(--terminal-accent-amber);
	}
	.tab-strip__btn:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: -2px;
	}

	.tab-strip__btn--active {
		color: var(--terminal-accent-amber);
		border-bottom-color: var(--terminal-accent-amber);
	}
</style>
