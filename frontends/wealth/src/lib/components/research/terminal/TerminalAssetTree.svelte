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
		background: var(--terminal-bg-panel);
		border-right: var(--terminal-border-hairline);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-secondary);
		min-width: 0;
	}

	.at-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 10px 12px 8px;
		border-bottom: var(--terminal-border-hairline);
		flex-shrink: 0;
	}

	.at-title {
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: 0.1em;
		color: var(--terminal-fg-tertiary);
		text-transform: uppercase;
	}

	.at-count {
		font-family: var(--terminal-font-mono);
		font-size: 9px;
		color: var(--terminal-fg-muted);
		font-variant-numeric: tabular-nums;
	}

	.at-search {
		padding: 8px 10px;
		border-bottom: 1px solid var(--terminal-fg-disabled);
		flex-shrink: 0;
	}

	.at-search-input {
		width: 100%;
		background: var(--terminal-bg-panel-sunken);
		border: var(--terminal-border-hairline);
		color: var(--terminal-fg-secondary);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		padding: 5px 8px;
		outline: none;
		border-radius: var(--terminal-radius-none);
	}
	.at-search-input:focus {
		border-color: var(--terminal-accent-cyan-dim);
	}
	.at-search-input::placeholder {
		color: var(--terminal-fg-muted);
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
		border-bottom: 1px solid var(--terminal-fg-disabled);
		color: inherit;
		font-family: inherit;
		font-size: inherit;
		cursor: pointer;
		text-align: left;
		min-width: 0;
	}
	.at-row:hover {
		background: var(--terminal-bg-panel-raised);
	}
	.at-row.selected {
		background: var(--terminal-bg-overlay);
	}
	.at-row.dim {
		opacity: 0.55;
	}

	.at-ticker {
		font-family: var(--terminal-font-mono);
		font-weight: 700;
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-primary);
		letter-spacing: 0.04em;
	}
	.at-row.selected .at-ticker {
		color: var(--terminal-accent-cyan);
	}

	.at-name {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		min-width: 0;
	}

	.at-aum {
		font-family: var(--terminal-font-mono);
		font-size: 9px;
		color: var(--terminal-fg-tertiary);
		font-variant-numeric: tabular-nums;
		flex-shrink: 0;
	}

	.at-empty {
		padding: 24px 14px;
		text-align: center;
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-muted);
		font-style: italic;
	}
	.at-err {
		color: var(--terminal-status-error);
		font-style: normal;
	}
</style>
