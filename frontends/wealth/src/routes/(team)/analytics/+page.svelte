<!--
  Analytics — Correlações + Backtest & Walk-Forward + Pareto Frontier + What-If + Atribuição
  Figma frame "Correlações + Pareto frontier" (node 1:2)
-->
<script lang="ts">
	import {
		PageHeader,
		PageTabs,
		SectionCard,
		MetricCard,
		EmptyState,
		HeatmapChart,
		ChartContainer,
		Button,
	} from "@netz/ui";
	import type { PageData } from "./$types";
	import { createClientApiClient } from "$lib/api/client";
	import { getContext } from "svelte";
	import { goto } from "$app/navigation";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	// ── Types ────────────────────────────────────────────────────────────────

	type CorrelationMatrix = {
		matrix: number[][];
		labels: string[];
		stats?: {
			sharpe_ratio?: number | null;
			avg_correlation?: number | null;
			effective_n?: number | null;
			max_pair_correlation?: number | null;
			max_pair_names?: [string, string] | null;
			min_pair_correlation?: number | null;
			min_pair_names?: [string, string] | null;
			benchmark_correlation?: number | null;
		};
	};

	type CorrelationRegime = {
		profile: string;
		points: { fund_name: string; cvar_pct: number; return_pct: number; is_portfolio?: boolean }[];
		frontier: { cvar_pct: number; return_pct: number }[];
	};

	// ── Server data ──────────────────────────────────────────────────────────

	let correlation = $state.raw(data.correlation as CorrelationMatrix | null);
	let correlationRegime = $state.raw(data.correlationRegime as CorrelationRegime | null);

	// ── Filters ──────────────────────────────────────────────────────────────

	const PROFILES = [
		{ value: "conservative", label: "Conservador" },
		{ value: "moderate", label: "Moderado" },
		{ value: "growth", label: "Growth" },
	];

	let selectedPortfolio = $state(data.profile as string ?? "moderate");
	let dateFrom = $state("");
	let dateTo = $state("");

	function applyPortfolioFilter(profile: string) {
		selectedPortfolio = profile;
		goto(`?portfolio=${profile}`, { replaceState: true, invalidateAll: true });
	}

	// ── Tabs ─────────────────────────────────────────────────────────────────

	const TABS = [
		{ value: "correlacoes", label: "Correlações" },
		{ value: "backtest", label: "Backtest & Walk-Forward" },
		{ value: "pareto", label: "Pareto Frontier" },
		{ value: "whatif", label: "What-If Scenarios" },
		{ value: "atribuicao", label: "Atribuição de Performance" },
	];

	// ── Correlações KPIs ────────────────────────────────────────────────────

	let stats = $derived(correlation?.stats ?? null);

	function fmtNum(v: number | null | undefined, decimals = 2): string {
		if (v === null || v === undefined) return "—";
		return v.toFixed(decimals);
	}

	function fmtPct(v: number | null | undefined): string {
		if (v === null || v === undefined) return "—";
		return `${(v * 100).toFixed(1)}%`;
	}

	// ── Heatmap data ─────────────────────────────────────────────────────────

	let heatmapData = $derived(
		correlation
			? {
					matrix: correlation.matrix,
					xLabels: correlation.labels,
					yLabels: correlation.labels,
				}
			: null,
	);

	// ── Pareto Frontier chart (multi-series via ChartContainer) ──────────────

	let paretoOption = $derived.by(() => {
		const fundPoints = (correlationRegime?.points ?? [])
			.filter((p) => !p.is_portfolio)
			.map((p) => ({ value: [p.cvar_pct, p.return_pct], name: p.fund_name }));

		const portfolioPoints = (correlationRegime?.points ?? [])
			.filter((p) => p.is_portfolio)
			.map((p) => ({ value: [p.cvar_pct, p.return_pct], name: p.fund_name }));

		const frontierLine = (correlationRegime?.frontier ?? [])
			.map((p) => [p.cvar_pct, p.return_pct] as [number, number]);

		const hasFrontier = frontierLine.length > 0;

		return {
			tooltip: {
				trigger: "item",
				formatter: (params: { seriesName?: string; name?: string; value: [number, number] }) => {
					const label = params.name ? `<strong>${params.name}</strong><br/>` : "";
					return `${label}CVaR: ${params.value[0].toFixed(2)}%<br/>Retorno: ${params.value[1].toFixed(2)}%`;
				},
			},
			legend: {
				bottom: 0,
				textStyle: { fontSize: 11 },
				data: ["Fundos", "Portfólios", ...(hasFrontier ? ["Fronteira Eficiente"] : [])],
			},
			grid: { left: 60, right: 20, top: 20, bottom: 50 },
			xAxis: {
				type: "value",
				name: "Risco (CVaR %)",
				nameLocation: "middle",
				nameGap: 32,
				axisLabel: { fontSize: 11, formatter: (v: number) => `${v}%` },
			},
			yAxis: {
				type: "value",
				name: "Retorno (%)",
				nameLocation: "middle",
				nameGap: 48,
				axisLabel: { fontSize: 11, formatter: (v: number) => `${v}%` },
			},
			series: [
				{
					name: "Fundos",
					type: "scatter",
					data: fundPoints,
					symbolSize: 10,
					itemStyle: { color: "var(--netz-brand-primary, #1E40AF)" },
				},
				{
					name: "Portfólios",
					type: "scatter",
					data: portfolioPoints,
					symbolSize: 14,
					symbol: "diamond",
					itemStyle: { color: "var(--netz-warning, #F59E0B)" },
				},
				...(hasFrontier
					? [
							{
								name: "Fronteira Eficiente",
								type: "line",
								data: frontierLine,
								lineStyle: { type: "dashed", color: "var(--netz-brand-secondary, #60A5FA)", width: 2 },
								itemStyle: { color: "var(--netz-brand-secondary, #60A5FA)" },
								showSymbol: false,
							},
						]
					: []),
			],
		} as Record<string, unknown>;
	});

	// ── Backtest state (with polling for pending results) ─────────────────────

	let backtestRunning = $state(false);
	let backtestResult = $state<Record<string, unknown> | null>(null);
	let backtestError = $state<string | null>(null);
	let backtestPollStop: (() => void) | null = null;

	async function triggerBacktest() {
		backtestRunning = true;
		backtestResult = null;
		backtestError = null;
		try {
			const api = createClientApiClient(getToken);
			const result = await api.post("/analytics/backtest", {
				profile: selectedPortfolio,
			}) as Record<string, unknown>;

			// If pending, poll for results using createPoller (auto-cleanup on unmount)
			if (result.status === "pending" && result.run_id) {
				const runId = String(result.run_id);
				pollBacktestResult(runId);
			} else {
				backtestResult = result;
				backtestRunning = false;
			}
		} catch (e) {
			backtestError = e instanceof Error ? e.message : "Backtest failed";
			backtestRunning = false;
		}
	}

	function pollBacktestResult(runId: string) {
		const api = createClientApiClient(getToken);
		let stopped = false;

		backtestPollStop = () => { stopped = true; };

		(async () => {
			const maxAttempts = 12; // 60s total (5s x 12)
			for (let i = 0; i < maxAttempts; i++) {
				if (stopped) return;
				await new Promise(r => setTimeout(r, 5000));
				if (stopped) return;
				try {
					const result = await api.get<Record<string, unknown>>(`/analytics/backtest/${runId}`);
					if (result.status !== "pending") {
						backtestResult = result;
						backtestRunning = false;
						return;
					}
				} catch {
					break;
				}
			}
			backtestError = "Backtest timed out. Check back later.";
			backtestRunning = false;
		})();
	}

	// Cleanup polling on component destroy
	$effect(() => {
		return () => {
			backtestPollStop?.();
		};
	});

	// ── Optimization state ────────────────────────────────────────────────────

	let optimizationRunning = $state(false);
	let optimizationError = $state<string | null>(null);

	async function runOptimization() {
		optimizationRunning = true;
		optimizationError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post("/analytics/optimize", { profile: selectedPortfolio });
			goto(`?portfolio=${selectedPortfolio}`, { replaceState: true, invalidateAll: true });
		} catch (e) {
			optimizationError = e instanceof Error ? e.message : "Optimization failed";
		} finally {
			optimizationRunning = false;
		}
	}

	// ── Pareto optimization (180s timeout, duplicate prevention) ──────────────

	let paretoRunning = $state(false);
	let paretoError = $state<string | null>(null);

	async function runPareto() {
		if (paretoRunning) return; // prevent duplicate
		paretoRunning = true;
		paretoError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post("/analytics/optimize/pareto", { profile: selectedPortfolio }, { timeoutMs: 180_000 });
			goto(`?portfolio=${selectedPortfolio}`, { replaceState: true, invalidateAll: true });
		} catch (e) {
			if (e instanceof Error && e.message.includes("429")) {
				paretoError = "Server at capacity. Please try again in a few minutes.";
			} else if (e instanceof Error && e.message.includes("timeout")) {
				paretoError = "Optimization timed out. The server may still be processing.";
			} else {
				paretoError = e instanceof Error ? e.message : "Pareto optimization failed";
			}
		} finally {
			paretoRunning = false;
		}
	}

	// ── Pair correlation drill-down ──────────────────────────────────────────

	let pairDetail = $state<Record<string, unknown> | null>(null);
	let pairLoading = $state(false);
	let showPairPanel = $derived(pairDetail !== null);

	async function loadPairCorrelation(instA: string, instB: string) {
		pairLoading = true;
		try {
			const api = createClientApiClient(getToken);
			pairDetail = await api.get(`/analytics/correlation-regime/${selectedPortfolio}/pair/${encodeURIComponent(instA)}/${encodeURIComponent(instB)}`);
		} catch {
			pairDetail = null;
		} finally {
			pairLoading = false;
		}
	}

	// ── Attribution ──────────────────────────────────────────────────────────

	let attributionData = $state<Record<string, unknown> | null>(null);
	let attributionLoading = $state(false);
	let attributionLoaded = $state(false);
	let selectedFundId = $state("");

	async function loadAttribution() {
		if (!selectedFundId || attributionLoading) return;
		attributionLoading = true;
		try {
			const api = createClientApiClient(getToken);
			attributionData = await api.get(`/analytics/attribution/funds/${selectedFundId}/period`);
			attributionLoaded = true;
		} catch {
			attributionData = null;
		} finally {
			attributionLoading = false;
		}
	}
</script>

<div class="space-y-6 p-6">
	<!-- Page Header + Filters -->
	<PageHeader title="Analytics">
		{#snippet actions()}
			<!-- Portfolio dropdown -->
			<select
				class="rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface-elevated)] px-3 py-1.5 text-sm text-[var(--netz-text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--netz-brand-primary)]"
				value={selectedPortfolio}
				onchange={(e) => applyPortfolioFilter((e.target as HTMLSelectElement).value)}
			>
				{#each PROFILES as p (p.value)}
					<option value={p.value}>{p.label}</option>
				{/each}
			</select>

			<!-- Date range -->
			<input
				type="date"
				class="rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface-elevated)] px-3 py-1.5 text-sm text-[var(--netz-text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--netz-brand-primary)]"
				bind:value={dateFrom}
				aria-label="Data início"
			/>
			<span class="text-xs text-[var(--netz-text-muted)]">–</span>
			<input
				type="date"
				class="rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface-elevated)] px-3 py-1.5 text-sm text-[var(--netz-text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--netz-brand-primary)]"
				bind:value={dateTo}
				aria-label="Data fim"
			/>
		{/snippet}
	</PageHeader>

	<!-- 5-tab navigation -->
	<PageTabs tabs={TABS} defaultTab="correlacoes">
		{#snippet children(activeTab)}

			<!-- ═══════════════════════════════════════════════════════════════
			     Tab: Correlações
			     ═══════════════════════════════════════════════════════════════ -->
			{#if activeTab === "correlacoes"}
				<div class="space-y-6">
					<!-- KPI row — 6 MetricCards -->
					<div class="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-6">
						<MetricCard
							label="Sharpe Ratio"
							value={fmtNum(stats?.sharpe_ratio)}
							sublabel="Portfólio consolidado"
						/>
						<MetricCard
							label="Correlação Média"
							value={fmtNum(stats?.avg_correlation)}
							sublabel="Entre todos os pares"
						/>
						<MetricCard
							label="Diversificação Efetiva"
							value={fmtNum(stats?.effective_n, 1)}
							sublabel="N efetivo de ativos"
						/>
						<MetricCard
							label="Maior Correlação Par"
							value={fmtNum(stats?.max_pair_correlation)}
							sublabel={stats?.max_pair_names ? stats.max_pair_names.join(" / ") : "—"}
							status={stats?.max_pair_correlation !== null && stats?.max_pair_correlation !== undefined && stats.max_pair_correlation > 0.85 ? "warn" : undefined}
						/>
						<MetricCard
							label="Menor Correlação Par"
							value={fmtNum(stats?.min_pair_correlation)}
							sublabel={stats?.min_pair_names ? stats.min_pair_names.join(" / ") : "—"}
						/>
						<MetricCard
							label="Corr. Benchmark"
							value={fmtPct(stats?.benchmark_correlation)}
							sublabel="vs. índice de referência"
						/>
					</div>

					<!-- Heatmap -->
					<SectionCard title="Matriz de Correlação" subtitle="Correlação de Pearson entre retornos mensais dos fundos">
						{#if heatmapData && heatmapData.matrix.length > 0}
							<div class="h-[480px]">
								<HeatmapChart
									matrix={heatmapData.matrix}
									xLabels={heatmapData.xLabels}
									yLabels={heatmapData.yLabels}
									height={460}
								/>
							</div>
						{:else}
							<EmptyState
								title="Sem dados de correlação"
								message="A matriz de correlação será exibida após NAV histórico estar disponível para ao menos 2 fundos."
							/>
						{/if}
					</SectionCard>
				</div>

			<!-- ═══════════════════════════════════════════════════════════════
			     Tab: Backtest & Walk-Forward
			     ═══════════════════════════════════════════════════════════════ -->
			{:else if activeTab === "backtest"}
				<div class="space-y-6">
					<SectionCard title="Backtest" subtitle="Executar backtest histórico para o perfil selecionado">
						<div class="flex items-center gap-3">
							<Button
								onclick={triggerBacktest}
								disabled={backtestRunning}
								size="sm"
							>
								{backtestRunning ? "Executando… (polling a cada 5s)" : "Executar Backtest"}
							</Button>
						</div>
						{#if backtestError}
							<div class="mt-4 rounded-md border border-[var(--netz-status-error)] p-3 text-sm text-[var(--netz-status-error)]">
								{backtestError}
							</div>
						{/if}
						{#if backtestResult}
							<div class="mt-4 rounded-md bg-[var(--netz-surface-inset)] p-4">
								<p class="text-sm text-[var(--netz-text-secondary)]">
									Status: <span class="font-mono font-medium">{backtestResult.status ?? "—"}</span>
									{#if backtestResult.run_id}
										| Run ID: <span class="font-mono">{backtestResult.run_id}</span>
									{/if}
								</p>
								{#if backtestResult.metrics}
									<div class="mt-3 grid gap-2 sm:grid-cols-3">
										{#each Object.entries(backtestResult.metrics as Record<string, number>) as [key, value]}
											<div class="rounded bg-[var(--netz-surface)] p-2">
												<p class="text-xs text-[var(--netz-text-muted)]">{key}</p>
												<p class="text-sm font-medium text-[var(--netz-text-primary)]">{typeof value === "number" ? value.toFixed(4) : value}</p>
											</div>
										{/each}
									</div>
								{/if}
							</div>
						{/if}
					</SectionCard>

					<SectionCard title="Walk-Forward Validation" subtitle="Análise out-of-sample por janelas rolantes">
						<EmptyState
							title="Walk-Forward disponível em breve"
							message="A validação walk-forward será habilitada quando o backtest engine suportar janelas out-of-sample rolantes."
						/>
					</SectionCard>
				</div>

			<!-- ═══════════════════════════════════════════════════════════════
			     Tab: Pareto Frontier
			     ═══════════════════════════════════════════════════════════════ -->
			{:else if activeTab === "pareto"}
				<div class="space-y-6">
					<SectionCard title="Fronteira de Pareto — Risco × Retorno" subtitle="CVaR 95% no eixo X · Retorno anualizado no eixo Y">
						{#snippet actions()}
							<div class="flex gap-2">
								<Button
									onclick={runOptimization}
									disabled={optimizationRunning}
									size="sm"
								>
									{optimizationRunning ? "Otimizando…" : "Otimização rápida"}
								</Button>
								<Button
									onclick={runPareto}
									disabled={paretoRunning}
									size="sm"
									variant="outline"
								>
									{paretoRunning ? "Pareto… (até 2 min)" : "Multi-objetivo (Pareto)"}
								</Button>
							</div>
						{/snippet}
						{#if paretoError}
							<div class="mb-3 rounded-md border border-[var(--netz-status-error)] p-3 text-sm text-[var(--netz-status-error)]">
								{paretoError}
							</div>
						{/if}
						{#if optimizationError}
							<div class="mb-3 rounded-md border border-[var(--netz-status-error)] p-3 text-sm text-[var(--netz-status-error)]">
								{optimizationError}
							</div>
						{/if}

						<!-- Legend chips -->
						<div class="mb-4 flex flex-wrap gap-3">
							<div class="flex items-center gap-1.5">
								<span class="h-2.5 w-2.5 rounded-full bg-[var(--netz-brand-primary)]"></span>
								<span class="text-xs text-[var(--netz-text-muted)]">Fundos individuais</span>
							</div>
							<div class="flex items-center gap-1.5">
								<span class="h-2.5 w-2.5 rotate-45 bg-[var(--netz-warning)]" style="display:inline-block;"></span>
								<span class="text-xs text-[var(--netz-text-muted)]">Portfólios</span>
							</div>
							<div class="flex items-center gap-1.5">
								<span class="h-0.5 w-5 border-t-2 border-dashed border-[var(--netz-brand-secondary)]"></span>
								<span class="text-xs text-[var(--netz-text-muted)]">Fronteira eficiente</span>
							</div>
						</div>

						{#if correlationRegime && correlationRegime.points.length > 0}
							<div class="h-[400px]">
								<ChartContainer option={paretoOption} height={380} />
							</div>
						{:else}
							<EmptyState
								title="Sem dados de otimização"
								message="Clique em 'Executar otimização' para calcular a fronteira eficiente. Requer CVaR histórico de ao menos 3 fundos."
							/>
						{/if}
					</SectionCard>
				</div>

			<!-- ═══════════════════════════════════════════════════════════════
			     Tab: What-If Scenarios
			     ═══════════════════════════════════════════════════════════════ -->
			{:else if activeTab === "whatif"}
				<SectionCard title="What-If Scenarios" subtitle="Simulação de cenários e stress testing">
					<EmptyState
						title="Scenarios em desenvolvimento"
						message="A análise de cenários What-If será habilitada quando o stress_scenario_engine estiver integrado ao portfólio selecionado."
					/>
				</SectionCard>

			<!-- ═══════════════════════════════════════════════════════════════
			     Tab: Atribuição de Performance
			     ═══════════════════════════════════════════════════════════════ -->
			{:else if activeTab === "atribuicao"}
				<SectionCard title="Atribuição de Performance" subtitle="Decomposição de retorno por fator e classe de ativo">
					<div class="mb-4 flex items-center gap-3">
						<input
							type="text"
							class="rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface-elevated)] px-3 py-1.5 text-sm text-[var(--netz-text-primary)]"
							bind:value={selectedFundId}
							placeholder="Fund ID"
						/>
						<Button
							onclick={loadAttribution}
							disabled={attributionLoading || !selectedFundId}
							size="sm"
						>
							{attributionLoading ? "Loading..." : "Load Attribution"}
						</Button>
					</div>
					{#if attributionData}
						<div class="space-y-2">
							{#each Object.entries(attributionData) as [key, value]}
								{#if key !== "fund_id" && key !== "period"}
									<div class="flex items-center justify-between rounded-md bg-[var(--netz-surface-inset)] px-3 py-2 text-sm">
										<span class="text-[var(--netz-text-primary)]">{key}</span>
										<span class="font-mono text-[var(--netz-text-secondary)]">{typeof value === "number" ? value.toFixed(4) : String(value ?? "—")}</span>
									</div>
								{/if}
							{/each}
						</div>
					{:else if !attributionLoaded}
						<EmptyState
							title="Selecione um fundo"
							message="Insira o Fund ID e clique Load Attribution para ver a decomposição de retorno."
						/>
					{/if}
				</SectionCard>
			{/if}

		{/snippet}
	</PageTabs>
</div>
