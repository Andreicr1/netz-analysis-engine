<!--
  HoldingsView — Holdings Analysis group for the standalone Discovery Analysis
  page (Phase 6.3). Composes 5 ChartCards inside AnalysisGrid:

    1. Top 25 Holdings  (EnterpriseTable with Reverse action, span=2)
    2. Sector Composition (SectorTreemap)
    3. Holdings Distribution (TopHoldingsSunburst, span=2)
    4. Style Drift (StyleDriftFlow)
    5. Holdings Reverse Lookup (HoldingsNetworkChart, span=3, 520px)

  Fetches `/funds/{id}/analysis/holdings/top` + `/holdings/style-drift` in
  parallel on mount / fundId change, and `/holdings/{cusip}/reverse-lookup`
  whenever the user clicks a Reverse button in the holdings table. Both
  effects use AbortController cleanup.

  Private funds (no N-PORT) render an institutional empty state (no public
  holdings disclosure). No localStorage. No @netz/ui imports. Formatters via
  @investintell/ui.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { EnterpriseTable, formatPercent } from "@investintell/ui";
	import type { ColumnDef } from "@investintell/ui";
	import ChartCard from "./ChartCard.svelte";
	import AnalysisGrid from "./AnalysisGrid.svelte";
	import HoldingsNetworkChart from "$lib/components/charts/discovery/HoldingsNetworkChart.svelte";
	import TopHoldingsSunburst from "$lib/components/charts/discovery/TopHoldingsSunburst.svelte";
	import SectorTreemap from "$lib/components/charts/discovery/SectorTreemap.svelte";
	import StyleDriftFlow from "$lib/components/charts/discovery/StyleDriftFlow.svelte";
	import {
		fetchHoldingsTop,
		fetchStyleDrift,
		fetchReverseLookup,
	} from "$lib/discovery/analysis-api";

	interface Holding {
		issuer_name: string;
		cusip: string | null;
		sector: string | null;
		pct_of_nav: number;
		market_value: number | null;
	}
	interface SectorBreakdown {
		sector: string;
		weight: number;
		holdings_count: number;
	}
	interface HoldingsTopPayload {
		top_holdings: Holding[];
		sector_breakdown: SectorBreakdown[];
		as_of: string | null;
		disclosure: { has_holdings: boolean };
	}
	interface StyleDriftSector {
		name: string;
		weight: number;
	}
	interface StyleDriftSnapshot {
		quarter: string;
		sectors: StyleDriftSector[];
	}
	interface StyleDriftPayload {
		snapshots: StyleDriftSnapshot[];
	}
	interface ReverseNode {
		id: string;
		name: string;
		category: "holding" | "holder";
		symbolSize: number;
		value?: number;
		source?: string;
	}
	interface ReverseEdge {
		source: string;
		target: string;
	}
	interface ReverseLookupPayload {
		nodes: ReverseNode[];
		edges: ReverseEdge[];
		target_cusip: string;
	}

	interface Props {
		fundId: string;
	}

	let { fundId }: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let topData = $state<HoldingsTopPayload | null>(null);
	let driftData = $state<StyleDriftPayload | null>(null);
	let topError = $state<string | null>(null);

	let selectedCusip = $state<string | null>(null);
	let reverseData = $state<ReverseLookupPayload | null>(null);
	let reverseError = $state<string | null>(null);
	let reverseLoading = $state(false);

	// Fetch holdings/top + style-drift in parallel when fundId changes.
	$effect(() => {
		const id = fundId;
		if (!id || !getToken) return;
		const ctrl = new AbortController();
		topData = null;
		driftData = null;
		topError = null;
		selectedCusip = null;
		reverseData = null;

		Promise.all([
			fetchHoldingsTop(getToken, id, ctrl.signal),
			fetchStyleDrift(getToken, id, 8, ctrl.signal).catch(() => null),
		])
			.then(([top, drift]) => {
				topData = top as HoldingsTopPayload;
				driftData = drift as StyleDriftPayload | null;
			})
			.catch((e: unknown) => {
				if (e instanceof Error && e.name !== "AbortError") {
					topError = e.message;
				}
			});
		return () => ctrl.abort();
	});

	// Fetch reverse-lookup whenever selectedCusip changes.
	$effect(() => {
		const cusip = selectedCusip;
		if (!cusip || !getToken) return;
		const ctrl = new AbortController();
		reverseData = null;
		reverseError = null;
		reverseLoading = true;
		fetchReverseLookup(getToken, cusip, ctrl.signal)
			.then((d) => {
				reverseData = d as ReverseLookupPayload;
				reverseLoading = false;
			})
			.catch((e: unknown) => {
				reverseLoading = false;
				if (e instanceof Error && e.name !== "AbortError") {
					reverseError = e.message;
				}
			});
		return () => ctrl.abort();
	});

	const hasHoldings = $derived(!!topData?.disclosure?.has_holdings);

	const holdingsRows = $derived((topData?.top_holdings ?? []).slice(0, 25));

	const columns: ColumnDef<Holding>[] = [
		{
			id: "name",
			header: "Issuer",
			width: "minmax(220px, 2fr)",
			accessor: (r) => r.issuer_name,
		},
		{
			id: "sector",
			header: "Sector",
			width: "minmax(140px, 1fr)",
			hideBelow: 1200,
			accessor: (r) => r.sector ?? "—",
		},
		{
			id: "weight",
			header: "Weight",
			numeric: true,
			width: "100px",
			accessor: (r) => r.pct_of_nav,
			format: (v) => (v == null ? "—" : formatPercent(v as number, 2)),
		},
		{
			id: "actions",
			header: "",
			width: "110px",
			align: "right",
			accessor: (r) => r.cusip,
		},
	];
</script>

{#if topError}
	<div class="hv-error">Failed to load holdings: {topError}</div>
{:else if !topData}
	<div class="hv-loading">Loading Holdings…</div>
{:else if !hasHoldings}
	<div class="hv-empty">
		<strong>No holdings disclosure</strong>
		<p>
			This fund reports via Form ADV filings only. Portfolio holdings are
			not publicly disclosed, so Top Holdings, Sector Composition, and
			Style Drift cannot be computed. Use the Returns &amp; Risk or Peer
			tabs instead.
		</p>
	</div>
{:else}
	{#snippet cellSnippet(row: Holding, col: ColumnDef<Holding>)}
		{#if col.id === "actions"}
			{#if row.cusip}
				<button
					type="button"
					class="rev-btn"
					class:active={row.cusip === selectedCusip}
					onclick={(e) => {
						e.stopPropagation();
						selectedCusip = row.cusip;
					}}
					title="Reverse lookup — who else holds this"
				>
					Reverse →
				</button>
			{:else}
				<span class="rev-na">—</span>
			{/if}
		{:else if col.format}
			{col.format(col.accessor(row), row)}
		{:else}
			{col.accessor(row) ?? ""}
		{/if}
	{/snippet}

	<AnalysisGrid>
		<ChartCard
			title="Top 25 Holdings"
			subtitle={topData.as_of ? `As of ${topData.as_of}` : undefined}
			span={2}
			minHeight="420px"
		>
			<EnterpriseTable
				rows={holdingsRows}
				{columns}
				rowKey={(r) => r.cusip ?? r.issuer_name}
				cell={cellSnippet}
			/>
		</ChartCard>

		<ChartCard title="Sector Composition">
			<SectorTreemap sectors={topData.sector_breakdown} />
		</ChartCard>

		<ChartCard
			title="Holdings Distribution"
			subtitle="Two-level sunburst: sector → issuer"
			span={2}
		>
			<TopHoldingsSunburst holdings={topData.top_holdings} />
		</ChartCard>

		<ChartCard title="Style Drift" subtitle="Last 8 quarters">
			{#if driftData && driftData.snapshots.length > 0}
				<StyleDriftFlow snapshots={driftData.snapshots} />
			{:else}
				<div class="hv-sub-empty">Not enough historical filings.</div>
			{/if}
		</ChartCard>

		<ChartCard
			title="Holdings Reverse Lookup"
			subtitle={selectedCusip
				? `CUSIP ${selectedCusip}`
				: "Click Reverse on a holding to see who else holds it"}
			span={3}
			minHeight="520px"
		>
			{#if !selectedCusip}
				<div class="hv-hint">
					Select a holding above and click the <strong>Reverse →</strong> button
					to render the holders network.
				</div>
			{:else if reverseError}
				<div class="hv-error">Failed to load: {reverseError}</div>
			{:else if reverseLoading || !reverseData}
				<div class="hv-loading">Loading reverse lookup…</div>
			{:else if reverseData.nodes.length <= 1}
				<div class="hv-hint">
					No other filers reported this CUSIP in the latest 13F/N-PORT batch.
				</div>
			{:else}
				<HoldingsNetworkChart
					nodes={reverseData.nodes}
					edges={reverseData.edges}
				/>
			{/if}
		</ChartCard>
	</AnalysisGrid>
{/if}

<style>
	.hv-error,
	.hv-loading,
	.hv-empty,
	.hv-hint,
	.hv-sub-empty {
		padding: 40px;
		text-align: center;
		color: var(--ii-text-muted);
		font-family: "Urbanist", system-ui, sans-serif;
		font-size: 12px;
	}
	.hv-sub-empty {
		padding: 24px;
	}
	.hv-empty strong {
		display: block;
		font-size: 14px;
		color: var(--ii-text-primary);
		margin-bottom: 8px;
	}
	.hv-empty p {
		max-width: 480px;
		margin: 0 auto;
		font-size: 12px;
		line-height: 1.6;
	}
	.rev-btn {
		font-family: "Urbanist", system-ui, sans-serif;
		font-size: 11px;
		font-weight: 600;
		padding: 4px 10px;
		border-radius: 4px;
		background: var(--ii-border-accent, rgba(0, 102, 255, 0.08));
		border: 1px solid var(--ii-brand-accent, #0066ff);
		color: var(--ii-brand-accent, #0066ff);
		cursor: pointer;
		transition: all 150ms;
	}
	.rev-btn:hover,
	.rev-btn.active {
		background: var(--ii-brand-accent, #0066ff);
		color: white;
	}
	.rev-na {
		color: var(--ii-text-muted);
		font-size: 11px;
	}
</style>
