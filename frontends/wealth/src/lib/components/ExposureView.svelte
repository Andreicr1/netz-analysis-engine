<!--
  ExposureView — geographic and sector allocation heatmaps per portfolio or manager.
  Self-loading component for embedding in Analytics tabs.
-->
<script lang="ts">
	import { SectionCard, HeatmapTable, EmptyState, Skeleton, formatPercent } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import { getContext } from "svelte";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	type ExposureMatrix = {
		dimension: string;
		aggregation: string;
		rows: string[];
		columns: string[];
		data: number[][];
	};

	type FundFreshness = {
		fund_name: string;
		last_updated_days: number;
	};

	type ExposureMetadata = {
		freshness: FundFreshness[];
	};

	let geoMatrix = $state<ExposureMatrix | null>(null);
	let sectorMatrix = $state<ExposureMatrix | null>(null);
	let metadata = $state<ExposureMetadata | null>(null);
	let aggregation = $state("portfolio");
	let loading = $state(true);

	function freshnessColor(days: number): string {
		if (days < 30) return "var(--netz-success)";
		if (days <= 60) return "var(--netz-warning)";
		return "var(--netz-danger)";
	}

	function freshnessBg(days: number): string {
		if (days < 30) return "var(--netz-success-subtle)";
		if (days <= 60) return "var(--netz-warning-subtle)";
		return "var(--netz-danger-subtle)";
	}

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
		<h3 class="text-sm font-semibold text-(--netz-text-primary)">Exposure Monitor</h3>
		<div
			class="flex items-center rounded-lg border border-(--netz-border) bg-(--netz-surface-inset) p-1"
			role="group"
			aria-label="Aggregation"
		>
			<button
				class="rounded-md px-3 py-1.5 text-sm font-medium transition-colors"
				class:bg-(--netz-surface-elevated)={aggregation === "portfolio"}
				class:text-(--netz-text-primary)={aggregation === "portfolio"}
				class:shadow-(--netz-shadow-1)={aggregation === "portfolio"}
				class:text-(--netz-text-muted)={aggregation !== "portfolio"}
				onclick={() => setAggregation("portfolio")}
			>
				Portfolios
			</button>
			<button
				class="rounded-md px-3 py-1.5 text-sm font-medium transition-colors"
				class:bg-(--netz-surface-elevated)={aggregation === "manager"}
				class:text-(--netz-text-primary)={aggregation === "manager"}
				class:shadow-(--netz-shadow-1)={aggregation === "manager"}
				class:text-(--netz-text-muted)={aggregation !== "manager"}
				onclick={() => setAggregation("manager")}
			>
				By Manager
			</button>
		</div>
	</div>

	{#if loading}
		<div class="grid gap-4 xl:grid-cols-2">
			<Skeleton class="h-64 rounded-xl" />
			<Skeleton class="h-64 rounded-xl" />
		</div>
	{:else}
		<!-- Heatmap grids -->
		<div class="grid gap-4 xl:grid-cols-2">
			<SectionCard
				title="Geographic Exposure"
				subtitle="Weight by region · from latest processed portfolio"
			>
				{#if geoMatrix && geoMatrix.rows.length > 0}
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
				{#if sectorMatrix && sectorMatrix.rows.length > 0}
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

		<!-- Data freshness badges -->
		{#if metadata && metadata.freshness.length > 0}
			<SectionCard
				title="Data Freshness"
				subtitle="Last update per fund · green < 30d · yellow 30–60d · red > 60d"
			>
				<div class="flex flex-wrap gap-2">
					{#each metadata.freshness as fund (fund.fund_name)}
						<div
							class="flex items-center gap-2 rounded-full px-3 py-1.5 text-sm font-medium"
							style:background-color={freshnessBg(fund.last_updated_days)}
						>
							<span class="text-(--netz-text-primary)">{fund.fund_name}</span>
							<span
								class="rounded-full px-2 py-0.5 text-xs font-semibold"
								style:color={freshnessColor(fund.last_updated_days)}
							>
								{fund.last_updated_days}d
							</span>
						</div>
					{/each}
				</div>
			</SectionCard>
		{/if}
	{/if}
</div>
