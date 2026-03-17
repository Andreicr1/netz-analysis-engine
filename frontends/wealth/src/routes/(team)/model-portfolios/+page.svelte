<!--
  Model Portfolios — sidebar list + inline detail.
  Figma frame "Model Portfolios com track-record" (node 1:5)
-->
<script lang="ts">
	import {
		EmptyState, PageHeader, StatusBadge, MetricCard, SectionCard,
		UtilizationBar, PeriodSelector,
	} from "@netz/ui";
	import { page } from "$app/stores";
	import { goto } from "$app/navigation";
	import type { PageData } from "./$types";
	import { createClientApiClient } from "@netz/ui/utils";

	let { data }: { data: PageData } = $props();

	type ModelPortfolio = {
		id: string;
		profile: string;
		display_name: string;
		description: string | null;
		benchmark_composite: string | null;
		inception_date: string | null;
		inception_nav: number;
		status: string;
		created_at: string;
	};

	let portfolios = $state.raw((data.modelPortfolios ?? []) as ModelPortfolio[]);

	// Selected portfolio from URL param
	const selectedId = $derived($page.url.searchParams.get("portfolio"));
	const selectedPortfolio = $derived(portfolios.find((p) => p.id === selectedId) ?? portfolios[0] ?? null);

	// Detail cache
	let detailCache = $state(new Map<string, Record<string, unknown>>());
	let loadingDetail = $state(false);

	// Load detail on selection change
	$effect(() => {
		if (!selectedPortfolio) return;
		const id = selectedPortfolio.id;
		if (detailCache.has(id)) return;

		loadingDetail = true;
		const token = data.token;
		const api = createClientApiClient(token);

		Promise.allSettled([
			api.get(`/model-portfolios/${id}/track-record`),
		]).then(([trackRecord]) => {
			const detail: Record<string, unknown> = {};
			if (trackRecord.status === "fulfilled") detail.trackRecord = trackRecord.value;
			detailCache.set(id, detail);
			detailCache = new Map(detailCache);
			loadingDetail = false;
		});
	});

	const currentDetail = $derived(selectedPortfolio ? detailCache.get(selectedPortfolio.id) : null);

	function selectPortfolio(id: string) {
		goto(`?portfolio=${id}`, { replaceState: true, noScroll: true });
	}

	// Profile badge colors
	const profileColors: Record<string, string> = {
		conservative: "var(--netz-success)",
		moderate: "var(--netz-info)",
		growth: "var(--netz-danger)",
	};
</script>

<div class="flex h-full">
	<!-- Sidebar: portfolio list (240px) -->
	<div class="flex w-60 shrink-0 flex-col border-r border-[var(--netz-border)] bg-[var(--netz-surface)]">
		<div class="flex items-center justify-between border-b border-[var(--netz-border)] px-4 py-3">
			<h2 class="text-xs font-semibold uppercase tracking-wider text-[var(--netz-text-muted)]">Portfólios</h2>
			<button
				class="rounded-md bg-[var(--netz-brand-primary)] px-2.5 py-1 text-xs font-medium text-white hover:opacity-90"
			>
				+ Novo
			</button>
		</div>

		<div class="flex-1 overflow-y-auto p-2">
			{#each portfolios as portfolio (portfolio.id)}
				<button
					class="mb-1 w-full rounded-lg p-3 text-left transition-colors {portfolio.id === selectedPortfolio?.id
						? 'border-l-2 border-[var(--netz-brand-primary)] bg-[var(--netz-surface-alt)]'
						: 'hover:bg-[var(--netz-surface-alt)]'}"
					onclick={() => selectPortfolio(portfolio.id)}
				>
					<div class="flex items-center justify-between">
						<p class="text-sm font-semibold text-[var(--netz-text-primary)]">{portfolio.display_name}</p>
						<span
							class="rounded-full px-1.5 py-0.5 text-[10px] font-semibold capitalize"
							style="color: {profileColors[portfolio.profile] ?? 'var(--netz-text-muted)'}; border: 1px solid currentColor;"
						>
							{portfolio.profile}
						</span>
					</div>
					<div class="mt-1 flex items-center gap-2 text-xs text-[var(--netz-text-muted)]">
						<span>NAV {portfolio.inception_nav.toFixed(0)}</span>
						<span>·</span>
						<StatusBadge status={portfolio.status} />
					</div>
				</button>
			{/each}
		</div>
	</div>

	<!-- Main: portfolio detail -->
	<div class="flex-1 overflow-y-auto p-6">
		{#if selectedPortfolio}
			<!-- Header -->
			<div class="mb-6 flex items-start justify-between">
				<div>
					<h1 class="text-2xl font-bold text-[var(--netz-text-primary)]">{selectedPortfolio.display_name}</h1>
					<p class="mt-1 text-sm text-[var(--netz-text-muted)]">
						Model Portfolio · {selectedPortfolio.benchmark_composite ?? "—"}
						{#if selectedPortfolio.inception_date}
							· Última revisão: {selectedPortfolio.inception_date}
						{/if}
					</p>
				</div>
				<div class="flex gap-2">
					<button class="rounded-md border border-[var(--netz-border)] px-3 py-1.5 text-xs font-medium text-[var(--netz-text-secondary)] hover:bg-[var(--netz-surface-alt)]">
						Fact-sheet ↓
					</button>
					<button class="rounded-md border border-[var(--netz-border)] px-3 py-1.5 text-xs font-medium text-[var(--netz-text-secondary)] hover:bg-[var(--netz-surface-alt)]">
						Rebalancear
					</button>
					<button class="rounded-md bg-[var(--netz-brand-primary)] px-3 py-1.5 text-xs font-medium text-white hover:opacity-90">
						Construir portfólio
					</button>
				</div>
			</div>

			<!-- 6 KPI Cards -->
			<div class="mb-6 grid gap-3 md:grid-cols-3 xl:grid-cols-6">
				<MetricCard label="NAV Atual" value="Base {selectedPortfolio.inception_nav.toFixed(0)}" />
				<MetricCard label="YTD" value="—" status="ok" />
				<MetricCard label="CVaR 95%" value="—" status="warn" sublabel="lim: —" />
				<MetricCard label="Sharpe" value="—" />
				<MetricCard label="Vol Anual" value="—" sublabel="rolling 12M" />
				<MetricCard label="Max Drawdown" value="—" status="breach" />
			</div>

			<!-- Track Record -->
			<SectionCard title="Track-Record — Retornos Periódicos" class="mb-6">
				<EmptyState
					title="Retornos periódicos indisponíveis"
					message="Retornos periódicos serão calculados quando dados de NAV histórico estiverem disponíveis."
				/>
			</SectionCard>

			<!-- Allocation by Block -->
			<SectionCard title="Alocação por Bloco" class="mb-6">
				<EmptyState
					title="Dados de alocação"
					message="Alocação por bloco será exibida quando a seleção de fundos estiver configurada."
				/>
			</SectionCard>

			<!-- Stress Scenarios -->
			<SectionCard title="Stress Scenarios">
				<EmptyState
					title="Cenários de stress"
					message="Cenários de stress serão exibidos quando dados de track-record estiverem disponíveis."
				/>
			</SectionCard>
		{:else}
			<EmptyState
				title="Nenhum portfólio"
				message="Crie um model portfolio para começar."
			/>
		{/if}
	</div>
</div>
