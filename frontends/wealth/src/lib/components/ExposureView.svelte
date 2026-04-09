<!--
  ExposureView — geographic and sector allocation heatmaps per portfolio or manager.
  Self-loading component for embedding in Analytics tabs.
-->
<script lang="ts">
	import { SectionCard, HeatmapTable, EmptyState, formatPercent, formatShortDate } from "@investintell/ui";
	import { Skeleton } from "@investintell/ui/components/ui/skeleton";
	import { createClientApiClient } from "$lib/api/client";
	import { getContext } from "svelte";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	type ExposureMatrix = {
		dimension: string;
		aggregation: string;
		rows: string[];
		columns: string[];
		data: number[][];
		is_empty: boolean;
		as_of: string | null;
	};

	type ExposureMetadata = {
		as_of: string | null;
		snapshot_count: number;
		profile_count: number;
	};

	let geoMatrix = $state<ExposureMatrix | null>(null);
	let sectorMatrix = $state<ExposureMatrix | null>(null);
	let metadata = $state<ExposureMetadata | null>(null);
	let aggregation = $state("portfolio");
	let loading = $state(true);

	let bothEmpty = $derived(
		!loading &&
			(geoMatrix?.is_empty !== false) &&
			(sectorMatrix?.is_empty !== false)
	);

	async function fetchData(agg: string) {
		loading = true;
		try {
			const api = createClientApiClient(getToken);
			const [geo, sector, meta] = await Promise.allSettled([
				api.get(`/wealth/exposure/matrix?dimension=geographic&aggregation=${agg}`),
				api.get(`/wealth/exposure/matrix?dimension=sector&aggregation=${agg}`),
				api.get("/wealth/exposure/metadata"),
			]);
			geoMatrix = geo.status === "fulfilled" ? (geo.value as ExposureMatrix) : null;
			sectorMatrix = sector.status === "fulfilled" ? (sector.value as ExposureMatrix) : null;
			metadata = meta.status === "fulfilled" ? (meta.value as ExposureMetadata) : null;
		} finally {
			loading = false;
		}
	}

	async function setAggregation(value: string) {
		aggregation = value;
		await fetchData(value);
	}

	function fmtWeight(v: number): string {
		return formatPercent(v, 1, "en-US");
	}

	// Load on mount
	fetchData("portfolio");
</script>

<div class="space-y-6">
	<!-- Aggregation toggle -->
	<div class="flex items-center justify-between">
		<h3 class="text-sm font-semibold text-(--ii-text-primary)">Exposure Monitor</h3>
		<div class="flex items-center gap-3">
			{#if metadata?.as_of}
				<span class="text-xs text-(--ii-text-muted)">
					as of {formatShortDate(metadata.as_of)}
				</span>
			{/if}
			<div
				class="flex items-center rounded-lg border border-(--ii-border) bg-(--ii-surface-inset) p-1"
				role="group"
				aria-label="Aggregation"
			>
				<button
					class="rounded-md px-3 py-1.5 text-sm font-medium transition-colors"
					class:bg-(--ii-surface-elevated)={aggregation === "portfolio"}
					class:text-(--ii-text-primary)={aggregation === "portfolio"}
					class:shadow-(--ii-shadow-1)={aggregation === "portfolio"}
					class:text-(--ii-text-muted)={aggregation !== "portfolio"}
					onclick={() => setAggregation("portfolio")}
				>
					Portfolios
				</button>
				<button
					class="rounded-md px-3 py-1.5 text-sm font-medium transition-colors"
					class:bg-(--ii-surface-elevated)={aggregation === "manager"}
					class:text-(--ii-text-primary)={aggregation === "manager"}
					class:shadow-(--ii-shadow-1)={aggregation === "manager"}
					class:text-(--ii-text-muted)={aggregation !== "manager"}
					onclick={() => setAggregation("manager")}
				>
					By Manager
				</button>
			</div>
		</div>
	</div>

	{#if loading}
		<div class="grid gap-4 xl:grid-cols-2">
			<Skeleton class="h-64 rounded-xl" />
			<Skeleton class="h-64 rounded-xl" />
		</div>
	{:else if bothEmpty}
		<SectionCard title="Exposure Monitor">
			<div class="flex flex-col items-center justify-center py-20 text-center">
				<p class="text-lg font-medium text-(--ii-text-primary)">Sem posições para exibir</p>
				{#if metadata && metadata.profile_count === 0}
					<p class="mt-2 text-sm text-(--ii-text-muted)">
						Configure um Model Portfolio antes de visualizar a exposição.
					</p>
					<a
						href="/portfolio"
						class="mt-4 inline-flex items-center rounded-lg bg-(--ii-accent) px-4 py-2 text-sm font-medium text-white hover:opacity-90 transition-opacity"
					>
						Ir para Model Portfolios
					</a>
				{:else}
					<p class="mt-2 text-sm text-(--ii-text-muted)">
						Os portfolios existem mas ainda não têm posições calculadas.
						Aguarde o próximo ciclo do engine ou acione a construção manual.
					</p>
				{/if}
			</div>
		</SectionCard>
	{:else}
		<!-- Heatmap grids -->
		<div class="grid gap-4 xl:grid-cols-2">
			<SectionCard
				title="Geographic Exposure"
				subtitle="Weight by region · from latest processed portfolio"
			>
				{#if geoMatrix && !geoMatrix.is_empty && geoMatrix.rows.length > 0}
					<HeatmapTable
						rows={geoMatrix.rows}
						columns={geoMatrix.columns}
						data={geoMatrix.data}
						formatCell={fmtWeight}
					/>
				{:else}
					<EmptyState
						title="No geographic data"
						message="Geographic exposure will appear after portfolio processing."
					/>
				{/if}
			</SectionCard>

			<SectionCard
				title="Sector Exposure"
				subtitle="Weight by asset class · from latest processed portfolio"
			>
				{#if sectorMatrix && !sectorMatrix.is_empty && sectorMatrix.rows.length > 0}
					<HeatmapTable
						rows={sectorMatrix.rows}
						columns={sectorMatrix.columns}
						data={sectorMatrix.data}
						formatCell={fmtWeight}
					/>
				{:else}
					<EmptyState
						title="No sector data"
						message="Sector exposure will appear after portfolio processing."
					/>
				{/if}
			</SectionCard>
		</div>
	{/if}
</div>
