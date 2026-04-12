<!--
	LayoutCage.svelte — canonical 24px black-margin frame.
	======================================================

	Source of truth: docs/plans/2026-04-11-terminal-unification-master-plan.md
		§1.4 TerminalShell + layer taxonomy, Appendix G file structure.

	Replaces the ad-hoc `calc(100vh - 88px)` + `padding: 24px` pattern
	that was scattered across every (terminal) page and layout file
	(see memory/feedback_layout_cage_pattern.md for the incident
	that produced this rule).

	Pure presentational primitive: fills its grid cell (TerminalShell
	owns the viewport math and hands the cage a constrained height
	via its grid layout) and paints a var(--terminal-space-6) black
	margin on all sides. Children decide their own inner overflow.

	No state, no effects, no derivations. Do NOT add chrome-height
	math here — that is TerminalShell's job.
-->
<script lang="ts">
	import type { Snippet } from "svelte";

	interface LayoutCageProps {
		children: Snippet;
		/**
		 * Optional class hook for consumers that need to compose their
		 * own layout modifiers (e.g., grid / flex setup) on top of the
		 * cage frame.
		 */
		class?: string;
		/**
		 * Density variant. "standard" (24px padding) for narrative
		 * surfaces; "compact" (8px) for data-dense grids.
		 */
		density?: "standard" | "compact";
	}

	let { children, class: className = "", density = "standard" }: LayoutCageProps = $props();
</script>

<div class="lc-cage lc-cage--{density} {className}">
	{@render children()}
</div>

<style>
	.lc-cage {
		position: relative;
		box-sizing: border-box;
		width: 100%;
		height: 100%;
		background: var(--terminal-bg-void);
		overflow: hidden;
	}

	.lc-cage--standard {
		padding: var(--terminal-space-6); /* 24px — narrative surfaces */
	}

	.lc-cage--compact {
		padding: var(--terminal-space-2); /* 8px — data-dense surfaces */
	}
</style>
