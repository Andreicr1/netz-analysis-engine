<!--
  AnalysisGrid — responsive grid for ChartCard tiles on the Analysis page.
  Uses container queries (parent sets `container-type: inline-size`) so
  breakpoints are relative to the main column width, not the viewport. This
  matters because the FilterRail may or may not be open, and the FCL is out
  of scope on this standalone page.
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
