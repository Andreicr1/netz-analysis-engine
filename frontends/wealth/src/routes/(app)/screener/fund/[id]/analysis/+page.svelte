<!--
  Screener fund Risk Analysis — tab content under /screener/fund/[id].

  Structurally identical to the Discovery-era
  /discovery/funds/[external_id]/analysis/+page.svelte — same three
  view groups (Returns & Risk, Holdings Analysis, Peer Analysis),
  same FilterRail, same AnalysisFilters, same client-side fetch
  pattern for the fund header.

  Differences from the Discovery version:
    - Uses `data.fundId` (= params.id) instead of params.external_id
    - No "← Discovery" back link (the parent fund-detail +layout.svelte
      owns the "Fact Sheet ↔ Risk Analysis" tab nav)
    - No .analysis-page outer wrapper — the parent layout provides the
      rounded scroll container for both tabs
    - Header reflects the Screener visual language (consistent with
      the Fact Sheet header)

  All three child views (ReturnsRiskView, HoldingsView, PeerView) and
  the chart components they render were unblocked by:
    - Branch #1 (backend resolver walks class_id → series_id → CIK so
      registered US funds resolve to live data, plus the holdings
      queries now filter by series_id so umbrella trusts no longer
      melt across sibling series)
    - Branch #2 (frontend chart components now read the correct
      fund_risk_metrics column names, use @investintell/ui formatters
      instead of .toFixed, and relabel raw quant jargon to plain
      institutional English per the smart-backend/dumb-frontend rule)
-->
<script lang="ts">
	import { page } from "$app/state";
	import { goto } from "$app/navigation";
	import { getContext } from "svelte";
	import { FilterRail } from "@investintell/ui";
	import AnalysisFilters from "$lib/components/discovery/analysis/AnalysisFilters.svelte";
	import ReturnsRiskView from "$lib/components/discovery/analysis/ReturnsRiskView.svelte";
	import HoldingsView from "$lib/components/discovery/analysis/HoldingsView.svelte";
	import PeerView from "$lib/components/discovery/analysis/PeerView.svelte";
	import { fetchFundFactSheet } from "$lib/discovery/api";
	import type { AnalysisWindow } from "$lib/discovery/analysis-api";

	type Group = "returns-risk" | "holdings" | "peer";

	let { data } = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	const group = $derived(
		(page.url.searchParams.get("group") ?? data.initialGroup ?? "returns-risk") as Group,
	);
	const window: AnalysisWindow = $derived(
		(page.url.searchParams.get("window") ?? data.initialWindow ?? "3y") as AnalysisWindow,
	);

	// ── Client-side fact-sheet fetch (Clerk token only available in the browser). ──
	// Re-uses the same `/screener/catalog/:id/fact-sheet` endpoint the floating
	// preview Sheet on /screener hits, so the browser cache will serve the
	// second fetch from memory when the user flips between Fact Sheet and Risk
	// Analysis tabs.
	let header = $state<unknown>(null);
	let headerError = $state<string | null>(null);

	$effect(() => {
		const fid = data.fundId;
		if (!fid) return;
		const ctrl = new AbortController();
		header = null;
		headerError = null;
		fetchFundFactSheet(getToken, fid, ctrl.signal)
			.then((h) => {
				header = h;
			})
			.catch((e: unknown) => {
				if ((e as Error).name !== "AbortError") {
					headerError = (e as Error).message;
				}
			});
		return () => ctrl.abort();
	});

	const fundName = $derived(
		(header as { fund?: { name?: string } } | null)?.fund?.name ?? data.fundId,
	);
	const fundTicker = $derived(
		(header as { fund?: { ticker?: string } } | null)?.fund?.ticker ?? "—",
	);
	const fundStrategy = $derived(
		(header as { fund?: { strategy_label?: string } } | null)?.fund?.strategy_label ??
			"—",
	);

	async function patch(updates: Record<string, string>): Promise<void> {
		const url = new URL(page.url);
		for (const [k, v] of Object.entries(updates)) url.searchParams.set(k, v);
		await goto(url, { replaceState: true, noScroll: true, keepFocus: true });
	}
</script>

<svelte:head>
	<title>{fundName} · Risk Analysis</title>
</svelte:head>

<section class="risk-root">
	<header class="risk-header">
		<div class="risk-titles">
			<h1>{fundName}</h1>
			<p>{fundTicker} · {fundStrategy}</p>
		</div>
		<nav class="risk-tabs" aria-label="Risk analysis view">
			<button
				type="button"
				class:active={group === "returns-risk"}
				onclick={() => patch({ group: "returns-risk" })}
			>
				Returns &amp; Risk
			</button>
			<button
				type="button"
				class:active={group === "holdings"}
				onclick={() => patch({ group: "holdings" })}
			>
				Holdings Analysis
			</button>
			<button
				type="button"
				class:active={group === "peer"}
				onclick={() => patch({ group: "peer" })}
			>
				Peer Analysis
			</button>
		</nav>
	</header>

	{#if headerError}
		<div class="risk-error">Failed to load fund header: {headerError}</div>
	{:else}
		<div class="risk-body">
			<FilterRail>
				{#snippet filters()}
					<AnalysisFilters
						{group}
						{window}
						onWindowChange={(w) => patch({ window: w })}
					/>
				{/snippet}
			</FilterRail>

			<main class="risk-main">
				{#if group === "returns-risk"}
					<ReturnsRiskView fundId={data.fundId} {window} />
				{:else if group === "holdings"}
					<HoldingsView fundId={data.fundId} />
				{:else}
					<PeerView fundId={data.fundId} />
				{/if}
			</main>
		</div>
	{/if}
</section>

<style>
	.risk-root {
		display: flex;
		flex-direction: column;
		min-height: 100%;
		background: var(--ii-bg, #0e0f13);
		font-family: "Urbanist", system-ui, sans-serif;
	}

	.risk-header {
		display: flex;
		align-items: flex-end;
		justify-content: space-between;
		padding: 20px 24px;
		border-bottom: 1px solid var(--ii-border-subtle, rgba(255, 255, 255, 0.08));
		gap: 24px;
		flex-shrink: 0;
	}
	.risk-titles h1 {
		font-size: 20px;
		font-weight: 700;
		margin: 0;
		color: var(--ii-text-primary, #f3f4f6);
		letter-spacing: -0.01em;
	}
	.risk-titles p {
		font-size: 12px;
		color: var(--ii-text-muted, #9ca3af);
		margin: 4px 0 0;
		font-variant-numeric: tabular-nums;
	}
	.risk-tabs {
		display: inline-flex;
		gap: 4px;
	}
	.risk-tabs button {
		font-family: inherit;
		font-size: 12px;
		font-weight: 600;
		padding: 8px 16px;
		border-radius: 999px;
		background: transparent;
		border: 1px solid var(--ii-border-subtle, rgba(255, 255, 255, 0.14));
		color: var(--ii-text-muted, #9ca3af);
		cursor: pointer;
		transition: background 120ms, color 120ms, border-color 120ms;
	}
	.risk-tabs button:hover {
		color: #f3f4f6;
		border-color: rgba(255, 255, 255, 0.28);
	}
	.risk-tabs button.active {
		background: var(--ii-brand-accent, #0066ff);
		color: #ffffff;
		border-color: var(--ii-brand-accent, #0066ff);
	}

	.risk-body {
		display: flex;
		flex: 1;
		min-height: 0;
	}
	.risk-main {
		flex: 1;
		min-width: 0;
		container-type: inline-size;
	}
	.risk-error {
		padding: 48px 24px;
		text-align: center;
		color: var(--ii-text-muted, #9ca3af);
		font-size: 13px;
	}
</style>
