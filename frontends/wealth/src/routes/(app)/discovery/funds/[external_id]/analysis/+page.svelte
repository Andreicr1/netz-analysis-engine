<!--
  Standalone Analysis page for a single discovery fund.

  Layout:
    ┌──────────────────────── ap-header ────────────────────────┐
    │ ← back   Fund name / ticker / strategy      [tabs group]   │
    ├─────────── FilterRail ────────────┬─── ap-main (grid) ─────┤
    │  Time window                       │  6 ChartCards on       │
    │  Group-specific filters            │  AnalysisGrid          │
    └────────────────────────────────────┴────────────────────────┘

  URL-driven state: `group` (returns-risk|holdings|peer), `window`
  (1y|3y|5y|max). Mutations via `goto` with
  `{ replaceState, noScroll, keepFocus }` so filter interaction does not
  push history entries. No localStorage.

  Phases 6 and 7 will wire Holdings and Peer views — for now both show a
  placeholder.
-->
<script lang="ts">
	import { page } from "$app/state";
	import { goto } from "$app/navigation";
	import { FilterRail } from "@investintell/ui";
	import AnalysisFilters from "$lib/components/discovery/analysis/AnalysisFilters.svelte";
	import ReturnsRiskView from "$lib/components/discovery/analysis/ReturnsRiskView.svelte";
	import HoldingsView from "$lib/components/discovery/analysis/HoldingsView.svelte";
	import type { AnalysisWindow } from "$lib/discovery/analysis-api";

	type Group = "returns-risk" | "holdings" | "peer";

	let { data } = $props();

	const group = $derived(
		(page.url.searchParams.get("group") ?? data.initialGroup ?? "returns-risk") as Group,
	);
	const window: AnalysisWindow = $derived(
		(page.url.searchParams.get("window") ?? data.initialWindow ?? "3y") as AnalysisWindow,
	);

	const header = $derived(data.status === "ok" ? data.header : null);
	const fundName = $derived(
		(header as { fund?: { name?: string } } | null)?.fund?.name ?? data.fundId,
	);
	const fundTicker = $derived(
		(header as { fund?: { ticker?: string } } | null)?.fund?.ticker ?? "—",
	);
	const fundStrategy = $derived(
		(header as { fund?: { strategy_label?: string } } | null)?.fund
			?.strategy_label ?? "—",
	);

	async function patch(updates: Record<string, string>) {
		const url = new URL(page.url);
		for (const [k, v] of Object.entries(updates)) url.searchParams.set(k, v);
		await goto(url, { replaceState: true, noScroll: true, keepFocus: true });
	}
</script>

<svelte:head><title>Analysis — {fundName}</title></svelte:head>

<div class="analysis-page">
	<header class="ap-header">
		<div class="ap-back">
			<a href="/discovery?fund={encodeURIComponent(data.fundId)}">← Discovery</a>
		</div>
		<div class="ap-titles">
			<h1>{fundName}</h1>
			<p>{fundTicker} · {fundStrategy}</p>
		</div>
		<nav class="ap-tabs" aria-label="Analysis groups">
			<button
				class:active={group === "returns-risk"}
				onclick={() => patch({ group: "returns-risk" })}
				type="button">Returns &amp; Risk</button
			>
			<button
				class:active={group === "holdings"}
				onclick={() => patch({ group: "holdings" })}
				type="button">Holdings Analysis</button
			>
			<button
				class:active={group === "peer"}
				onclick={() => patch({ group: "peer" })}
				type="button">Peer Analysis</button
			>
		</nav>
	</header>

	{#if data.status === "error"}
		<div class="ap-error">Failed to load fund header: {data.error}</div>
	{:else}
		<div class="ap-body">
			<FilterRail>
				{#snippet filters()}
					<AnalysisFilters
						{group}
						{window}
						onWindowChange={(w) => patch({ window: w })}
					/>
				{/snippet}
			</FilterRail>

			<main class="ap-main">
				{#if group === "returns-risk"}
					<ReturnsRiskView fundId={data.fundId} {window} />
				{:else if group === "holdings"}
					<HoldingsView fundId={data.fundId} />
				{:else}
					<div class="ap-placeholder">Peer Analysis — Phase 7</div>
				{/if}
			</main>
		</div>
	{/if}
</div>

<style>
	.analysis-page {
		display: flex;
		flex-direction: column;
		height: calc(100vh - 88px);
		background: var(--ii-bg-canvas, #0e0f13);
		font-family: "Urbanist", system-ui, sans-serif;
	}
	.ap-header {
		display: grid;
		grid-template-columns: 120px 1fr auto;
		align-items: center;
		padding: 16px 24px;
		border-bottom: 1px solid var(--ii-border-subtle);
		gap: 24px;
		flex-shrink: 0;
	}
	.ap-back a {
		color: var(--ii-text-muted);
		font-size: 12px;
		text-decoration: none;
	}
	.ap-back a:hover {
		color: var(--ii-accent);
	}
	.ap-titles h1 {
		font-size: 18px;
		font-weight: 600;
		margin: 0;
	}
	.ap-titles p {
		font-size: 11px;
		color: var(--ii-text-muted);
		margin: 2px 0 0;
		font-variant-numeric: tabular-nums;
	}
	.ap-tabs {
		display: inline-flex;
		gap: 4px;
	}
	.ap-tabs button {
		font-family: inherit;
		font-size: 12px;
		font-weight: 600;
		padding: 8px 16px;
		border-radius: 999px;
		background: transparent;
		border: 1px solid var(--ii-border-subtle);
		color: var(--ii-text-muted);
		cursor: pointer;
	}
	.ap-tabs button.active {
		background: var(--ii-accent);
		color: white;
		border-color: var(--ii-accent);
	}
	.ap-body {
		display: flex;
		flex: 1;
		min-height: 0;
	}
	.ap-main {
		flex: 1;
		min-width: 0;
		overflow-y: auto;
		container-type: inline-size;
	}
	.ap-placeholder {
		padding: 80px 40px;
		text-align: center;
		color: var(--ii-text-muted);
	}
	.ap-error {
		padding: 40px;
		text-align: center;
		color: var(--ii-text-muted);
	}
</style>
