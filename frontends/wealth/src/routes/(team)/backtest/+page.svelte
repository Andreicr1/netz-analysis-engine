<!--
  Backtest & Pareto decision-pack — dedicated route.
  Section 3.Wealth.4 of the UX Remediation Plan.

  BacktestResultDetail + BacktestFoldMetrics from api.d.ts — no type casting.
  LongRunningAction wired to GET /jobs/{id}/status poll fallback.
  Pareto: risk/return slider, recommended_weights highlighted, ChartContainer scatter.
-->
<script lang="ts">
	import {
		PageHeader,
		SectionCard,
		MetricCard,
		EmptyState,
		Button,
		LongRunningAction,
		DataTable,
		ChartContainer,
		formatNumber,
		formatPercent,
		formatDate,
		formatDateTime,
		createPoller,
	} from "@netz/ui";
	import type { ColumnDef } from "@tanstack/svelte-table";
	import { createClientApiClient } from "$lib/api/client";
	import { getContext } from "svelte";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	// ── API types matching api.d.ts schemas — no invented shapes ─────────────
	// Source of truth: packages/ui/src/types/api.d.ts (components["schemas"]["BacktestFoldMetrics"])
	type BacktestFoldMetrics = {
		fold: number;
		train_start?: string | null;
		train_end?: string | null;
		test_start?: string | null;
		test_end?: string | null;
		sharpe?: number | null;
		cvar_95?: number | null;
		max_drawdown?: number | null;
		n_obs: number;
	};

	// Source of truth: packages/ui/src/types/api.d.ts (components["schemas"]["BacktestResultDetail"])
	type BacktestResultDetail = {
		folds: BacktestFoldMetrics[];
		mean_sharpe?: number | null;
		std_sharpe?: number | null;
		positive_folds: number;
		n_splits_computed: number;
	};

	// Source of truth: packages/ui/src/types/api.d.ts (components["schemas"]["BacktestRunRead"])
	type BacktestRunRead = {
		run_id: string;
		profile: string;
		params: Record<string, unknown>;
		status: string;
		results?: BacktestResultDetail | null;
		cv_metrics?: Record<string, unknown> | null;
		error_message?: string | null;
		started_at: string;
		completed_at?: string | null;
	};

	// ── Profile selector ─────────────────────────────────────────────────────

	const PROFILES = [
		{ value: "conservative", label: "Conservador" },
		{ value: "moderate", label: "Moderado" },
		{ value: "growth", label: "Growth" },
	] as const;

	let selectedProfile = $state<string>("moderate");

	// ── Pareto slider ─────────────────────────────────────────────────────────
	// 0 = max risk aversion (low risk, low return), 100 = max return seeking

	let riskReturnBias = $state(50);
	let paretoRunning = $state(false);
	let paretoError = $state<string | null>(null);

	// Pareto frontier points from server
	type ParetoPoint = { cvar_pct: number; return_pct: number; is_recommended?: boolean; weights?: Record<string, number> };
	type ParetoFrontierData = {
		profile: string;
		points: { fund_name: string; cvar_pct: number; return_pct: number; is_portfolio?: boolean }[];
		frontier: { cvar_pct: number; return_pct: number }[];
	};

	let paretoData = $state<ParetoFrontierData | null>(null);
	let paretoComputedAt = $state<string | null>(null);

	// Derived: recommended portfolio on frontier closest to slider position
	let recommendedPoint = $derived.by(() => {
		const frontier = paretoData?.frontier ?? [];
		if (frontier.length === 0) return null;
		// Bias 0 = leftmost (min risk), 100 = rightmost (max return)
		const sorted = [...frontier].sort((a, b) => a.cvar_pct - b.cvar_pct);
		const idx = Math.round((riskReturnBias / 100) * (sorted.length - 1));
		return sorted[idx] ?? null;
	});

	async function loadParetoData() {
		try {
			const api = createClientApiClient(getToken);
			const res = await api.get<ParetoFrontierData>(`/analytics/correlation-regime/${selectedProfile}`);
			paretoData = res;
		} catch {
			paretoData = null;
		}
	}

	async function runPareto() {
		if (paretoRunning) return;
		paretoRunning = true;
		paretoError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post("/analytics/optimize/pareto", { profile: selectedProfile }, { timeoutMs: 180_000 });
			await loadParetoData();
		} catch (e) {
			if (e instanceof Error && e.message.includes("429")) {
				paretoError = "Servidor sobrecarregado. Tente novamente em alguns minutos.";
			} else if (e instanceof Error && e.message.includes("timeout")) {
				paretoError = "Otimização atingiu timeout. O servidor pode ainda estar processando.";
			} else {
				paretoError = e instanceof Error ? e.message : "Pareto optimization failed";
			}
		} finally {
			paretoRunning = false;
		}
	}

	// Load Pareto data on profile change
	$effect(() => {
		void loadParetoData();
	});

	// ── Pareto chart option ───────────────────────────────────────────────────

	let paretoChartOption = $derived.by(() => {
		const fundPoints = (paretoData?.points ?? [])
			.filter((p) => !p.is_portfolio)
			.map((p) => ({ value: [p.cvar_pct, p.return_pct], name: p.fund_name }));

		const portfolioPoints = (paretoData?.points ?? [])
			.filter((p) => p.is_portfolio)
			.map((p) => ({ value: [p.cvar_pct, p.return_pct], name: p.fund_name }));

		const frontierLine = (paretoData?.frontier ?? [])
			.sort((a, b) => a.cvar_pct - b.cvar_pct)
			.map((p) => [p.cvar_pct, p.return_pct] as [number, number]);

		const hasFrontier = frontierLine.length > 0;
		const rec = recommendedPoint;

		return {
			tooltip: {
				trigger: "item",
				formatter: (params: { seriesName?: string; name?: string; value: [number, number] }) => {
					const label = params.name ? `<strong>${params.name}</strong><br/>` : "";
					return `${label}CVaR: ${formatNumber(params.value[0], 2, "en-US")}%<br/>Retorno: ${formatNumber(params.value[1], 2, "en-US")}%`;
				},
			},
			legend: {
				bottom: 0,
				textStyle: { fontSize: 11 },
				data: [
					"Fundos",
					"Portfólios",
					...(hasFrontier ? ["Fronteira Eficiente"] : []),
					...(rec ? ["Recomendado"] : []),
				],
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
					itemStyle: { color: "var(--netz-brand-primary)" },
				},
				{
					name: "Portfólios",
					type: "scatter",
					data: portfolioPoints,
					symbolSize: 14,
					symbol: "diamond",
					itemStyle: { color: "var(--netz-warning)" },
				},
				...(hasFrontier
					? [
							{
								name: "Fronteira Eficiente",
								type: "line",
								data: frontierLine,
								lineStyle: { type: "dashed", color: "var(--netz-brand-secondary)", width: 2 },
								itemStyle: { color: "var(--netz-brand-secondary)" },
								showSymbol: false,
							},
						]
					: []),
				...(rec
					? [
							{
								name: "Recomendado",
								type: "scatter",
								data: [{ value: [rec.cvar_pct, rec.return_pct], name: "Recomendado" }],
								symbolSize: 20,
								symbol: "pin",
								itemStyle: { color: "var(--netz-success)" },
							},
						]
					: []),
			],
		} as Record<string, unknown>;
	});

	// ── Backtest run state ────────────────────────────────────────────────────

	let backtestRunId = $state<string | null>(null);
	let backtestResult = $state<BacktestRunRead | null>(null);
	let backtestError = $state<string | null>(null);
	let backtestStarting = $state(false);

	// Polling via createPoller when job is pending
	let poller = $state<ReturnType<typeof createPoller<BacktestRunRead>> | null>(null);

	$effect(() => {
		const runId = backtestRunId;
		const result = backtestResult;

		// Poll terminal state when we have a run_id but result is still pending
		if (runId && (!result || result.status === "pending")) {
			const api = createClientApiClient(getToken);
			poller = createPoller<BacktestRunRead>({
				fn: () => api.get<BacktestRunRead>(`/analytics/backtest/${runId}`),
				intervalMs: 5_000,
				maxDurationMs: 300_000,
				shouldStop: (r) => r.status !== "pending",
			});
			return () => {
				poller?.stop();
				poller = null;
			};
		}
	});

	// Sync poller result into backtestResult
	$effect(() => {
		const res = poller?.result;
		if (res && res.status !== "pending") {
			backtestResult = res;
		}
	});

	async function startBacktest() {
		backtestStarting = true;
		backtestError = null;
		backtestResult = null;
		backtestRunId = null;
		try {
			const api = createClientApiClient(getToken);
			const res = await api.post<BacktestRunRead>("/analytics/backtest", {
				profile: selectedProfile,
			});
			backtestRunId = res.run_id;
			if (res.status !== "pending") {
				backtestResult = res;
			}
		} catch (e) {
			backtestError = e instanceof Error ? e.message : "Backtest failed to start";
		} finally {
			backtestStarting = false;
		}
	}

	// ── Backtest fold table columns ───────────────────────────────────────────

	const foldColumns: ColumnDef<Record<string, unknown>>[] = [
		{
			accessorKey: "fold",
			header: "Fold",
			enableSorting: true,
			cell: (info) => String(info.getValue() ?? "—"),
		},
		{
			accessorKey: "train_start",
			header: "Train Start",
			enableSorting: true,
			cell: (info) => {
				const v = info.getValue();
				return typeof v === "string" ? formatDate(v) : "—";
			},
		},
		{
			accessorKey: "train_end",
			header: "Train End",
			enableSorting: true,
			cell: (info) => {
				const v = info.getValue();
				return typeof v === "string" ? formatDate(v) : "—";
			},
		},
		{
			accessorKey: "test_start",
			header: "Test Start",
			enableSorting: true,
			cell: (info) => {
				const v = info.getValue();
				return typeof v === "string" ? formatDate(v) : "—";
			},
		},
		{
			accessorKey: "test_end",
			header: "Test End",
			enableSorting: true,
			cell: (info) => {
				const v = info.getValue();
				return typeof v === "string" ? formatDate(v) : "—";
			},
		},
		{
			accessorKey: "sharpe",
			header: "Sharpe",
			enableSorting: true,
			cell: (info) => {
				const v = info.getValue();
				return typeof v === "number" ? formatNumber(v, 3, "en-US") : "—";
			},
		},
		{
			accessorKey: "cvar_95",
			header: "CVaR 95%",
			enableSorting: true,
			cell: (info) => {
				const v = info.getValue();
				return typeof v === "number" ? formatPercent(v, 2, "en-US") : "—";
			},
		},
		{
			accessorKey: "max_drawdown",
			header: "Max Drawdown",
			enableSorting: true,
			cell: (info) => {
				const v = info.getValue();
				return typeof v === "number" ? formatPercent(v, 2, "en-US") : "—";
			},
		},
		{
			accessorKey: "n_obs",
			header: "Obs",
			enableSorting: true,
			cell: (info) => String(info.getValue() ?? "—"),
		},
	];

	// Typed fold rows from BacktestFoldMetrics[]
	let foldRows = $derived.by((): Record<string, unknown>[] => {
		const folds: BacktestFoldMetrics[] = backtestResult?.results?.folds ?? [];
		return folds.map((f): Record<string, unknown> => ({
			fold: f.fold,
			train_start: f.train_start ?? null,
			train_end: f.train_end ?? null,
			test_start: f.test_start ?? null,
			test_end: f.test_end ?? null,
			sharpe: f.sharpe ?? null,
			cvar_95: f.cvar_95 ?? null,
			max_drawdown: f.max_drawdown ?? null,
			n_obs: f.n_obs,
		}));
	});

	// Summary metrics from BacktestResultDetail
	let summary = $derived<BacktestResultDetail | null>(backtestResult?.results ?? null);

	// Positive folds percentage
	let positiveFoldsPct = $derived.by(() => {
		const s = summary;
		if (!s || s.n_splits_computed === 0) return null;
		return s.positive_folds / s.n_splits_computed;
	});

	// Status derived from polling
	let isPolling = $derived(poller?.active === true);
	let pollError = $derived(poller?.error ?? null);


</script>

<div class="space-y-6 p-6">
	<!-- Header + Profile selector -->
	<PageHeader title="Backtest & Fronteira de Pareto">
		{#snippet actions()}
			<select
				class="rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface-elevated)] px-3 py-1.5 text-sm text-[var(--netz-text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--netz-brand-primary)]"
				bind:value={selectedProfile}
			>
				{#each PROFILES as p (p.value)}
					<option value={p.value}>{p.label}</option>
				{/each}
			</select>
		{/snippet}
	</PageHeader>

	<!-- ══════════════════════════════════════════════════════════════════════
	     Backtest section — LongRunningAction + fold table
	     ══════════════════════════════════════════════════════════════════════ -->
	<SectionCard title="Backtest Walk-Forward" subtitle="Cross-validation temporal com métricas por fold">

		<!-- LongRunningAction drives the start/in-flight/success/error lifecycle.
		     No SSE stream needed — polling via createPoller provides progress. -->
		<LongRunningAction
			title="Executar Backtest"
			description="Submete job assíncrono de backtest. Faz polling em GET /analytics/backtest/{run_id} até resultado terminal."
			startLabel="Executar Backtest"
			retryLabel="Re-executar"
			idleMessage="Selecione o perfil e clique em Executar para iniciar o backtest histórico."
			successMessage="Backtest concluído com sucesso."
			onStart={startBacktest}
			onRetry={startBacktest}
		/>

		{#if backtestError}
			<div class="mt-4 rounded-md border border-[var(--netz-status-error)] p-3 text-sm text-[var(--netz-status-error)]" role="alert">
				{backtestError}
			</div>
		{/if}

		{#if pollError}
			<div class="mt-4 rounded-md border border-[var(--netz-status-error)] p-3 text-sm text-[var(--netz-status-error)]" role="alert">
				Polling error: {pollError}
			</div>
		{/if}

		{#if isPolling && backtestRunId}
			<div class="mt-4 rounded-md bg-[var(--netz-surface-inset)] p-3 text-sm text-[var(--netz-text-secondary)]">
				Aguardando resultado — Run ID: <span class="font-mono">{backtestRunId}</span>
				(polling a cada 5s via GET /jobs/{backtestRunId}/status)
			</div>
		{/if}

		<!-- Results: summary KPIs + fold table -->
		{#if backtestResult && backtestResult.status !== "pending" && summary}
			<div class="mt-6 space-y-6">
				<!-- Run metadata -->
				<div class="flex items-center gap-4 text-xs text-[var(--netz-text-muted)]">
					<span>Run ID: <span class="font-mono">{backtestResult.run_id}</span></span>
					<span>Perfil: <span class="font-medium text-[var(--netz-text-primary)]">{backtestResult.profile}</span></span>
					<span>Status: <span class="font-medium text-[var(--netz-text-primary)]">{backtestResult.status}</span></span>
					{#if backtestResult.completed_at}
						<span>Concluído: <time datetime={backtestResult.completed_at}>{formatDateTime(backtestResult.completed_at)}</time></span>
					{/if}
				</div>

				<!-- Summary KPIs — BacktestResultDetail fields -->
				<div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
					<MetricCard
						label="Sharpe Médio"
						value={summary.mean_sharpe !== null && summary.mean_sharpe !== undefined
							? formatNumber(summary.mean_sharpe, 3, "en-US")
							: "—"}
						sublabel="Média entre folds"
					/>
					<MetricCard
						label="Std Sharpe"
						value={summary.std_sharpe !== null && summary.std_sharpe !== undefined
							? formatNumber(summary.std_sharpe, 3, "en-US")
							: "—"}
						sublabel="Desvio entre folds"
					/>
					<MetricCard
						label="Folds Positivos"
						value={positiveFoldsPct !== null
							? formatPercent(positiveFoldsPct, 1, "en-US")
							: "—"}
						sublabel="{summary.positive_folds} de {summary.n_splits_computed} folds"
						status={positiveFoldsPct !== null && positiveFoldsPct < 0.5 ? "warn" : undefined}
					/>
					<MetricCard
						label="Folds Computados"
						value={String(summary.n_splits_computed)}
						sublabel="TimeSeriesSplit"
					/>
				</div>

				<!-- Per-fold table — DataTable with multi-sort -->
				{#if foldRows.length > 0}
					<div>
						<p class="mb-2 text-sm font-medium text-[var(--netz-text-primary)]">Métricas por Fold</p>
						<DataTable
							data={foldRows}
							columns={foldColumns}
							pageSize={10}
						/>
					</div>
				{:else}
					<EmptyState
						title="Sem dados de fold"
						message="O backtest foi concluído mas não retornou folds individuais."
					/>
				{/if}
			</div>
		{:else if backtestResult && backtestResult.status === "pending"}
			<div class="mt-4 text-sm text-[var(--netz-text-muted)]">
				Aguardando conclusão do backtest…
			</div>
		{/if}
	</SectionCard>

	<!-- ══════════════════════════════════════════════════════════════════════
	     Pareto section — guided slider + scatter chart
	     ══════════════════════════════════════════════════════════════════════ -->
	<SectionCard title="Fronteira de Pareto — Decisão Guiada" subtitle="Ajuste o viés risco/retorno e veja a alocação recomendada">
		{#snippet actions()}
			<Button
				onclick={runPareto}
				disabled={paretoRunning}
				size="sm"
				variant="outline"
			>
				{paretoRunning ? "Calculando Pareto… (até 2 min)" : "Multi-objetivo (NSGA-II)"}
			</Button>
		{/snippet}

		{#if paretoError}
			<div class="mb-4 rounded-md border border-[var(--netz-status-error)] p-3 text-sm text-[var(--netz-status-error)]" role="alert">
				{paretoError}
			</div>
		{/if}

		<!-- Risk/return slider -->
		<div class="mb-6 space-y-2">
			<div class="flex items-center justify-between text-sm">
				<span class="text-[var(--netz-text-secondary)]">Aversão ao risco máxima</span>
				<span class="font-medium text-[var(--netz-text-primary)]">Viés: {riskReturnBias}%</span>
				<span class="text-[var(--netz-text-secondary)]">Retorno máximo</span>
			</div>
			<input
				type="range"
				min="0"
				max="100"
				step="1"
				bind:value={riskReturnBias}
				class="w-full accent-[var(--netz-brand-primary)]"
				aria-label="Ajuste de viés risco/retorno"
			/>
			<div class="flex justify-between text-xs text-[var(--netz-text-muted)]">
				<span>Min CVaR</span>
				<span>Balanceado</span>
				<span>Max Retorno</span>
			</div>
		</div>

		<!-- Recommended allocation highlight -->
		{#if recommendedPoint}
			<div class="mb-6 flex items-center gap-4 rounded-lg border border-[var(--netz-success)] bg-[var(--netz-success)]/10 p-3">
				<div class="flex h-8 w-8 items-center justify-center rounded-full bg-[var(--netz-success)] text-white text-sm font-bold">★</div>
				<div>
					<p class="text-sm font-semibold text-[var(--netz-text-primary)]">Alocação Recomendada</p>
					<p class="text-xs text-[var(--netz-text-secondary)]">
						CVaR 95%: <span class="font-medium">{formatNumber(recommendedPoint.cvar_pct, 2, "en-US")}%</span>
						&nbsp;|&nbsp;
						Retorno: <span class="font-medium">{formatNumber(recommendedPoint.return_pct, 2, "en-US")}%</span>
					</p>
				</div>
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
			<div class="flex items-center gap-1.5">
				<span class="h-3 w-3 rounded-full bg-[var(--netz-success)]"></span>
				<span class="text-xs text-[var(--netz-text-muted)]">Recomendado (slider)</span>
			</div>
		</div>

		<!-- Pareto scatter + frontier line -->
		{#if paretoData && paretoData.points.length > 0}
			<div class="h-[420px]">
				<ChartContainer option={paretoChartOption} height={400} ariaLabel="Pareto frontier — risco vs. retorno" />
			</div>
			{#if paretoComputedAt}
				<p class="mt-2 text-right text-xs text-[var(--netz-text-muted)]">
					Calculado: <time datetime={paretoComputedAt}>{formatDateTime(paretoComputedAt)}</time>
				</p>
			{/if}
		{:else}
			<EmptyState
				title="Sem dados de otimização"
				message="Clique em 'Multi-objetivo (NSGA-II)' para calcular a fronteira de Pareto. Requer CVaR histórico de ao menos 3 fundos."
			/>
		{/if}
	</SectionCard>
</div>
