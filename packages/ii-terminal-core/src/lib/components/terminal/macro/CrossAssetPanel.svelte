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
					<div class="cap-sector-header">
						<span>{SECTOR_LABELS[sector]}</span>
						<span>{group.length}</span>
					</div>
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
		height: 100%;
		overflow-y: auto;
		background: var(--ii-surface);
		font-family: var(--ii-font-mono);
	}
	.cap-loading {
		padding: 12px;
		color: var(--ii-text-muted);
		font-size: 10px;
		letter-spacing: var(--ii-terminal-tr-caps);
	}
	.cap-group {
		display: flex;
		flex-direction: column;
	}
	.cap-sector-header {
		position: sticky;
		top: 0;
		z-index: 1;
		display: flex;
		justify-content: space-between;
		padding: 4px 12px;
		border-left: 2px solid var(--ii-brand-primary);
		background: var(--ii-border-subtle);
		color: var(--ii-text-muted);
		font-size: 9px;
		font-weight: 700;
		letter-spacing: var(--ii-terminal-tr-caps);
	}
</style>
