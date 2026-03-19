<!--
  Exposure Monitor — geographic and sector allocation heatmaps per portfolio or manager.
  Two HeatmapTable grids side-by-side with aggregation toggle + freshness badges.
-->
<script lang="ts">
	import { PageHeader, SectionCard, HeatmapTable, EmptyState, formatPercent } from "@netz/ui";
	import { goto } from "$app/navigation";
	import { page } from "$app/state";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();

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

	let geoMatrix = $derived(data.geoMatrix as ExposureMatrix | null);
	let sectorMatrix = $derived(data.sectorMatrix as ExposureMatrix | null);
	let metadata = $derived(data.metadata as ExposureMetadata | null);
	// svelte-ignore state_referenced_locally
	let aggregation = $state(data.aggregation as string);

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

	async function setAggregation(value: string) {
		aggregation = value;
		await goto(`?aggregation=${value}`, { invalidateAll: true });
	}

	function fmtWeight(v: number): string {
		return formatPercent(v, 1, "en-US");
	}
</script>

<div class="space-y-(--netz-space-section-gap) p-(--netz-space-page-gutter)">
	<PageHeader title="Exposure Monitor">
		{#snippet actions()}
			<div
				class="flex items-center rounded-lg border border-(--netz-border) bg-(--netz-surface-inset) p-1"
				role="group"
				aria-label="Agregação"
			>
				<button
					class="rounded-md px-3 py-1.5 text-sm font-medium transition-colors"
					class:bg-(--netz-surface-elevated)={aggregation === "portfolio"}
					class:text-(--netz-text-primary)={aggregation === "portfolio"}
					class:shadow-(--netz-shadow-1)={aggregation === "portfolio"}
					class:text-(--netz-text-muted)={aggregation !== "portfolio"}
					onclick={() => setAggregation("portfolio")}
				>
					Portfólios
				</button>
				<button
					class="rounded-md px-3 py-1.5 text-sm font-medium transition-colors"
					class:bg-(--netz-surface-elevated)={aggregation === "manager"}
					class:text-(--netz-text-primary)={aggregation === "manager"}
					class:shadow-(--netz-shadow-1)={aggregation === "manager"}
					class:text-(--netz-text-muted)={aggregation !== "manager"}
					onclick={() => setAggregation("manager")}
				>
					Por gestor
				</button>
			</div>
		{/snippet}
	</PageHeader>

	<!-- Heatmap grids -->
	<div class="grid gap-4 xl:grid-cols-2">
		<!-- Geographic exposure -->
		<SectionCard
			title="Exposição Geográfica"
			subtitle="Peso por região · dados da última carteira processada"
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
					title="Sem dados geográficos"
					message="A exposição geográfica será exibida após o processamento das carteiras."
				/>
			{/if}
		</SectionCard>

		<!-- Sector exposure -->
		<SectionCard
			title="Exposição por Setor"
			subtitle="Peso por classe de ativo · dados da última carteira processada"
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
					title="Sem dados setoriais"
					message="A exposição setorial será exibida após o processamento das carteiras."
				/>
			{/if}
		</SectionCard>
	</div>

	<!-- Data freshness badges -->
	{#if metadata && metadata.freshness.length > 0}
		<SectionCard
			title="Atualização dos Dados"
			subtitle="Última atualização por fundo · verde < 30d · amarelo 30–60d · vermelho > 60d"
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
</div>
