<!--
  WorkbenchToolRibbon — compact tool switcher for the Live Workbench
  header. Phase 9 Block B.

  Renders a segmented button group bound to the ``activeTool`` prop.
  Clicking a tab invokes ``onToolChange(tool)``, which the parent
  +page.svelte wires to a URL query param patch via goto(). The
  ribbon itself owns NO state — same pure-presentation discipline
  as the Phase 8 LivePortfolioSidebar.

  WAI-ARIA: rendered as a role="tablist" with role="tab" children.
  Arrow-key navigation deferred — v1 uses mouse + explicit focus.
-->
<script lang="ts">
	import {
		WORKBENCH_TOOLS,
		WORKBENCH_TOOL_META,
		type WorkbenchTool,
	} from "./workbench-state";

	interface Props {
		activeTool: WorkbenchTool;
		onToolChange: (tool: WorkbenchTool) => void;
	}

	let { activeTool, onToolChange }: Props = $props();
</script>

<div class="wtr-root" role="tablist" aria-label="Workbench tools">
	{#each WORKBENCH_TOOLS as tool (tool)}
		{@const meta = WORKBENCH_TOOL_META[tool]}
		{@const isActive = activeTool === tool}
		<button
			type="button"
			role="tab"
			aria-selected={isActive}
			aria-label={meta.description}
			title={meta.description}
			class="wtr-tab"
			class:wtr-tab--active={isActive}
			onclick={() => onToolChange(tool)}
		>
			{meta.label}
		</button>
	{/each}
</div>

<style>
	.wtr-root {
		display: inline-flex;
		align-items: center;
		gap: 2px;
		padding: 2px;
		background: var(--ii-surface, #141519);
		border: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
		border-radius: 6px;
	}

	.wtr-tab {
		appearance: none;
		border: 0;
		background: transparent;
		color: var(--ii-text-muted, #85a0bd);
		font-family: inherit;
		font-size: 11px;
		font-weight: 600;
		letter-spacing: 0.02em;
		padding: 6px 12px;
		border-radius: 4px;
		cursor: pointer;
		transition: background-color 120ms ease, color 120ms ease;
		white-space: nowrap;
	}

	.wtr-tab:hover {
		color: var(--ii-text-primary, #ffffff);
		background: rgba(255, 255, 255, 0.04);
	}

	.wtr-tab:focus-visible {
		outline: 2px solid var(--ii-focus-ring, #2d7ef7);
		outline-offset: 2px;
	}

	.wtr-tab--active {
		background: var(--ii-brand-accent, #2d7ef7);
		color: #ffffff;
	}

	.wtr-tab--active:hover {
		background: var(--ii-brand-accent, #2d7ef7);
		color: #ffffff;
	}
</style>
