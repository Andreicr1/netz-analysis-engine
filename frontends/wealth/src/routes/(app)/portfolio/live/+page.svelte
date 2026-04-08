<!--
  /portfolio/live — Phase 5 Task 5.5 stub for the Live workbench.

  The full Bloomberg-terminal Live workbench (WorkbenchLayout +
  WorkbenchCoreChart + WeightVectorTable + AlertsFeedPanel +
  RebalanceSuggestionPanel) is built across Phase 8 (shell) and
  Phase 9 (data + components). This stub exists so the Phase 5
  PortfolioSubNav ribbon's "Live" pill can navigate without a 404 —
  the route's content is intentionally a placeholder until Phase 8
  lands.

  Per CLAUDE.md DL15 — no localStorage; no fabricated values; strict
  empty state.
-->
<script lang="ts">
	import { EmptyState } from "@investintell/ui";
</script>

<svelte:head>
	<title>Live Workbench — Coming Soon</title>
</svelte:head>

<div class="pl-stub">
	<EmptyState
		title="Live Workbench"
		message="The terminal-style Live monitoring workbench is on the roadmap. It will ship with WorkbenchCoreChart, the live price tick buffer, the unified alerts feed, and the rebalance suggestion drawer."
	/>
</div>

<style>
	.pl-stub {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 100%;
		min-height: 0;
		padding: 48px 24px;
		background: #0e0f13;
	}
</style>
