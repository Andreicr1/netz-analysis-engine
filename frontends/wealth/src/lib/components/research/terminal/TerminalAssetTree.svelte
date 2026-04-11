<!--
  TerminalAssetTree — searchable real-data fund browser.

  Flat list view over `/screener/catalog` with a debounced search box.
  Replaces the previous 3-level hardcoded tree (Portfolio → Class → Fund)
  with the actual universe of ~9k funds that have NAV history.

  Each row exposes `instrumentId` (global instruments_universe UUID),
  which the parent Research shell threads through to the chart so
  the `/risk/timeseries/{instrument_id}` endpoint can resolve it.
-->
<script module lang="ts">
	export interface TreeNode {
		id: string;                 // external_id from catalog (stable row key)
		instrumentId: string | null; // global instruments_universe UUID (null if not imported)
		label: string;               // fund name
		ticker: string | null;
		fundType: string;
		aum: number | null;
	}
</script>

<script lang="ts">
	import { getContext } from "svelte";
	import { formatNumber } from "@investintell/ui";
	import { createClientApiClient } from "$lib/api/client";

	interface Props {
		selectedId: string | null;
		onSelect: (node: TreeNode) => void;
	}

	let { selectedId, onSelect }: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

	interface UnifiedFundItem {
		external_id: string;
		instrument_id: string | null;
		name: string;
		ticker: string | null;
		fund_type: string;
		aum: number | null;
	}
	interface UnifiedCatalogPage {
		items: UnifiedFundItem[];
		total: number;
	}

	let searchQuery = $state("");
	let nodes = $state<TreeNode[]>([]);
	let total = $state(0);
	let loading = $state(false);
	let errorMessage = $state<string | null>(null);

	function toNode(raw: UnifiedFundItem): TreeNode {
		return {
			id: raw.external_id,
			instrumentId: raw.instrument_id,
			label: raw.name,
			ticker: raw.ticker,
			fundType: raw.fund_type,
			aum: raw.aum,
		};
	}

	let debounceHandle: ReturnType<typeof setTimeout> | null = null;
	let fetchSeq = 0;

	$effect(() => {
		const q = searchQuery.trim();

		if (debounceHandle) clearTimeout(debounceHandle);
		debounceHandle = setTimeout(async () => {
			const fetchId = ++fetchSeq;
			loading = true;
			errorMessage = null;

			const params: Record<string, string> = {
				in_universe: "true",
				page: "1",
				page_size: "150",
				sort: "aum_desc",
			};
			if (q.length > 0) params.q = q;

			try {
				const page = await api.get<UnifiedCatalogPage>("/screener/catalog", params);
				if (fetchId !== fetchSeq) return; // stale
				nodes = page.items.map(toNode);
				total = page.total;
			} catch (err) {
				if (fetchId !== fetchSeq) return;
				nodes = [];
				total = 0;
				errorMessage = err instanceof Error ? err.message : "Failed to load fund catalog";
			} finally {
				if (fetchId === fetchSeq) loading = false;
			}
		}, 250);

		return () => {
			if (debounceHandle) clearTimeout(debounceHandle);
		};
	});

	function fmtAum(n: number | null): string {
		if (n == null || n <= 0) return "";
		if (n >= 1e12) return formatNumber(n / 1e12, 1) + "T";
		if (n >= 1e9) return formatNumber(n / 1e9, 1) + "B";
		if (n >= 1e6) return formatNumber(n / 1e6, 0) + "M";
		return formatNumber(n, 0);
	}
</script>

<div class="at-root">
	<div class="at-header">
		<span class="at-title">ASSET BROWSER</span>
		<span class="at-count">{nodes.length} / {formatNumber(total, 0)}</span>
	</div>

	<div class="at-search">
		<input
			type="text"
			placeholder="Search ticker / name / manager"
			bind:value={searchQuery}
			class="at-search-input"
		/>
	</div>

	<div class="at-scroll">
		{#if errorMessage}
			<div class="at-empty at-err">{errorMessage}</div>
		{:else if loading && nodes.length === 0}
			<div class="at-empty">Loading catalog&hellip;</div>
		{:else if nodes.length === 0}
			<div class="at-empty">No funds match that search.</div>
		{:else}
			{#each nodes as node (node.id)}
				<button
					class="at-row"
					class:selected={selectedId === node.id}
					class:dim={!node.instrumentId}
					onclick={() => onSelect(node)}
					title={node.instrumentId ? node.label : `${node.label} (no NAV data)`}
				>
					<span class="at-ticker">{node.ticker ?? "—"}</span>
					<span class="at-name">{node.label}</span>
					<span class="at-aum">{fmtAum(node.aum)}</span>
				</button>
			{/each}
		{/if}
	</div>
</div>

<style>
	.at-root {
		display: flex;
		flex-direction: column;
		height: 100%;
		background: #0c1018;
		border-right: 1px solid rgba(255, 255, 255, 0.06);
		font-family: "Urbanist", system-ui, sans-serif;
		font-size: 11px;
		color: #c8d0dc;
		min-width: 0;
	}

	.at-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 10px 12px 8px;
		border-bottom: 1px solid rgba(255, 255, 255, 0.06);
		flex-shrink: 0;
	}

	.at-title {
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.1em;
		color: #5a6577;
		text-transform: uppercase;
	}

	.at-count {
		font-family: "JetBrains Mono", monospace;
		font-size: 9px;
		color: #3a4455;
		font-variant-numeric: tabular-nums;
	}

	.at-search {
		padding: 8px 10px;
		border-bottom: 1px solid rgba(255, 255, 255, 0.04);
		flex-shrink: 0;
	}

	.at-search-input {
		width: 100%;
		background: #05080f;
		border: 1px solid rgba(255, 255, 255, 0.08);
		color: #c8d0dc;
		font-family: "JetBrains Mono", monospace;
		font-size: 10px;
		padding: 5px 8px;
		outline: none;
	}
	.at-search-input:focus {
		border-color: rgba(45, 126, 247, 0.4);
	}
	.at-search-input::placeholder {
		color: #3a4455;
	}

	.at-scroll {
		flex: 1;
		overflow-y: auto;
		overflow-x: hidden;
		min-height: 0;
	}

	.at-row {
		display: grid;
		grid-template-columns: 56px 1fr auto;
		align-items: center;
		gap: 6px;
		width: 100%;
		padding: 5px 10px;
		background: transparent;
		border: none;
		border-bottom: 1px solid rgba(255, 255, 255, 0.02);
		color: inherit;
		font-family: inherit;
		font-size: inherit;
		cursor: pointer;
		text-align: left;
		min-width: 0;
	}
	.at-row:hover {
		background: rgba(45, 126, 247, 0.06);
	}
	.at-row.selected {
		background: rgba(45, 126, 247, 0.12);
	}
	.at-row.dim {
		opacity: 0.55;
	}

	.at-ticker {
		font-family: "JetBrains Mono", monospace;
		font-weight: 700;
		font-size: 10px;
		color: #e2e8f0;
		letter-spacing: 0.04em;
	}
	.at-row.selected .at-ticker {
		color: #93bbfc;
	}

	.at-name {
		font-size: 10px;
		color: #8a94a6;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		min-width: 0;
	}

	.at-aum {
		font-family: "JetBrains Mono", monospace;
		font-size: 9px;
		color: #5a6577;
		font-variant-numeric: tabular-nums;
		flex-shrink: 0;
	}

	.at-empty {
		padding: 24px 14px;
		text-align: center;
		font-size: 11px;
		color: #3a4455;
		font-style: italic;
	}
	.at-err {
		color: #ef4444;
		font-style: normal;
	}
</style>
