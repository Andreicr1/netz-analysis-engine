<!--
  AnalysisGrid — responsive grid for ChartCard tiles.

  Part of the Analytics primitive set in @investintell/ui (promoted from
  `frontends/wealth/src/lib/components/discovery/analysis/AnalysisGrid.svelte`
  in Phase 4 Task 4.0 of the portfolio-enterprise-workbench plan).

  Uses container queries (parent sets `container-type: inline-size`) so
  the breakpoints are relative to the main column width, not the viewport.
  That matters because the surrounding FilterRail may or may not be open,
  and any FCL that hosts this grid can change its width independently of
  the viewport.
-->
<script lang="ts">
	import type { Snippet } from "svelte";

	interface Props {
		children: Snippet;
	}

	let { children }: Props = $props();
</script>

<div class="ag-root">{@render children()}</div>

<style>
	.ag-root {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 20px;
		padding: 24px;
		min-height: 0;
	}
	@container (max-width: 1400px) {
		.ag-root {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}
		.ag-root :global(.cc-card[data-span="3"]) {
			grid-column: span 2;
		}
	}
	@container (max-width: 1000px) {
		.ag-root {
			grid-template-columns: 1fr;
		}
		.ag-root :global(.cc-card[data-span="2"]),
		.ag-root :global(.cc-card[data-span="3"]) {
			grid-column: span 1;
		}
	}
</style>
