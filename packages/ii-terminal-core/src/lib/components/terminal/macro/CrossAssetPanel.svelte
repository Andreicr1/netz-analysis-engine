<script lang="ts">
	import MiniCard from "./MiniCard.svelte";

	export interface CrossAssetPoint {
		symbol: string;
		name: string;
		sector: "RATES" | "FX" | "EQUITY" | "COMMODITY" | "CREDIT";
		lastValue: number | null;
		changePct: number | null;
		unit: string;
		sparkline: number[];
	}

	interface Props {
		assets: CrossAssetPoint[];
		loading?: boolean;
		onAssetSelect?: (asset: CrossAssetPoint) => void;
	}

	let { assets, loading = false, onAssetSelect }: Props = $props();

	const SECTORS: Array<CrossAssetPoint["sector"]> = [
		"RATES",
		"FX",
		"EQUITY",
		"COMMODITY",
		"CREDIT",
	];

	const SECTOR_LABELS: Record<CrossAssetPoint["sector"], string> = {
		RATES: "RATES",
		FX: "FX",
		EQUITY: "EQUITY",
		COMMODITY: "CMDTY",
		CREDIT: "CREDIT",
	};

	const grouped = $derived(
		SECTORS.reduce<Record<string, CrossAssetPoint[]>>((acc, sector) => {
			acc[sector] = assets.filter((asset) => asset.sector === sector);
			return acc;
		}, {}),
	);
</script>

<div class="cap-root">
	{#if loading}
		<div class="cap-loading">LOADING...</div>
	{:else}
		{#each SECTORS as sector (sector)}
			{@const group = grouped[sector] ?? []}
			{#if group.length > 0}
				<section class="cap-group" aria-label={SECTOR_LABELS[sector]}>
					<div class="cap-sector-header">{SECTOR_LABELS[sector]}</div>
					{#each group as asset (asset.symbol)}
						<MiniCard
							symbol={asset.symbol}
							name={asset.name}
							lastValue={asset.lastValue}
							changePct={asset.changePct}
							unit={asset.unit}
							sparkline={asset.sparkline}
							onclick={() => onAssetSelect?.(asset)}
						/>
					{/each}
				</section>
			{/if}
		{/each}
	{/if}
</div>

<style>
	.cap-root {
		display: flex;
		flex-direction: column;
		gap: 1px;
		height: 100%;
		overflow-y: auto;
		background: var(--terminal-bg-panel);
		font-family: var(--terminal-font-mono);
	}
	.cap-loading {
		padding: var(--terminal-space-3);
		color: var(--terminal-fg-tertiary);
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
	}
	.cap-group {
		display: flex;
		flex-direction: column;
	}
	.cap-sector-header {
		padding: 2px var(--terminal-space-2);
		border-left: 2px solid var(--terminal-accent-amber);
		background: var(--terminal-bg-panel-sunken);
		color: var(--terminal-fg-tertiary);
		font-size: var(--terminal-text-10);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
	}
</style>
