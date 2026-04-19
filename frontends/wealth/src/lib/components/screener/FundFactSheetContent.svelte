<!--
  FundFactSheetContent — Brutalist Institutional Fund Analysis.
  Enforces 1px grid gaps, rounded-none, and font-mono text-11px.
  Injects Tail Risk, EVestment Stats, Distribution and Rolling Returns.
-->
<script lang="ts">
	import { ArrowLeft } from "lucide-svelte";
	import { formatCompact, formatPercent, formatDate, formatNumber } from "@investintell/ui";
	import { PanelEmptyState, PanelErrorState } from "@investintell/ui/runtime";
	import { UNIVERSE_LABELS } from "$wealth/types/catalog";
	import NavPerformanceChart from "$wealth/components/charts/NavPerformanceChart.svelte";
	import SectorAllocationChart from "$wealth/components/charts/SectorAllocationChart.svelte";
	import SectorAllocationTreemap from "$wealth/components/charts/SectorAllocationTreemap.svelte";
	import FundScoringRadar from "$wealth/components/charts/FundScoringRadar.svelte";
	import DecileBoxplot from "$wealth/components/charts/DecileBoxplot.svelte";
	import ReturnDistributionChart from "$wealth/components/charts/ReturnDistributionChart.svelte";
	import RollingReturnsChart from "$wealth/components/charts/RollingReturnsChart.svelte";
	import { getContext, onMount } from "svelte";
	import "./factsheet.css";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	interface RouteDataShape {
		data: Record<string, unknown> | null;
		error?: {
			code?: string;
			message: string;
			recoverable: boolean;
		} | null;
	}

	interface Props {
		routeData: RouteDataShape;
		showBackButton?: boolean;
		onBack?: () => void;
		backLabel?: string;
		onDownloadPdf?: () => void | Promise<void>;
		pdfLoading?: boolean;
		onRetry?: () => void;
	}

	let {
		routeData,
		showBackButton = false,
		onBack,
		backLabel = "Back",
		onDownloadPdf,
		pdfLoading = false,
		onRetry,
	}: Props = $props();

	// ── Defensive derived accessors ──
	const factSheet = $derived(routeData.data as Record<string, any> | null);
	const fund = $derived(factSheet?.fund ?? null);
	const team = $derived((factSheet?.team as any[] | undefined) ?? []);
	const top_holdings = $derived((factSheet?.top_holdings as any[] | undefined) ?? []);
	const annual_returns = $derived((factSheet?.annual_returns as any[] | undefined) ?? []);
	const nav_history = $derived((factSheet?.nav_history as any[] | undefined) ?? []);
	const sector_history = $derived((factSheet?.sector_history as any[] | undefined) ?? []);
	const share_classes = $derived((factSheet?.share_classes as any[] | undefined) ?? []);
	const scoring_metrics = $derived(factSheet?.scoring_metrics ?? null);
	const strategy_narrative = $derived(factSheet?.strategy_narrative ?? null);

	// ── Analytics Fetching (Raio-X Expansion) ──
	let analytics = $state<any>(null);
	let analyticsLoading = $state(false);

	$effect(() => {
		if (fund?.id) {
			fetchAnalytics(fund.id);
		}
	});

	async function fetchAnalytics(id: string) {
		analyticsLoading = true;
		try {
			const token = getToken ? await getToken() : "";
			const apiBase = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
			const res = await fetch(`${apiBase}/wealth/entity-analytics/${id}?window=1y`, {
				headers: { Authorization: `Bearer ${token}` }
			});
			if (res.ok) {
				analytics = await res.json();
			}
		} catch (e) {
			console.error("Failed to fetch analytics", e);
		} finally {
			analyticsLoading = false;
		}
	}

	// ── Derived KPI values ──
	const latestNav = $derived(nav_history.at(-1)?.nav ?? null);
	const prevNav = $derived(nav_history.at(-2)?.nav ?? null);
	const change1d = $derived(
		latestNav != null && prevNav != null && prevNav !== 0
			? (latestNav - prevNav) / prevNav
			: null,
	);
	const asOfDate = $derived(nav_history.at(-1)?.nav_date ?? null);

	function formatAum(val: number | null | undefined): string {
		if (val == null) return "—";
		return formatCompact(val);
	}
</script>

{#if routeData.error}
	<div class="fs-container flex flex-col gap-[1px] bg-[#222]">
		{#if showBackButton && onBack}
			<button onclick={onBack} class="fs-back fs-no-print p-2 bg-black text-white hover:bg-[#222]" type="button">
				<ArrowLeft size={16} />
				<span>{backLabel}</span>
			</button>
		{/if}
		<PanelErrorState
			title="LOAD FAILED"
			message={routeData.error.message}
			onRetry={routeData.error.recoverable ? onRetry : undefined}
		/>
	</div>
{:else if !fund}
	<div class="fs-container flex flex-col gap-[1px] bg-[#222]">
		{#if showBackButton && onBack}
			<button onclick={onBack} class="fs-back fs-no-print p-2 bg-black text-white hover:bg-[#222]" type="button">
				<ArrowLeft size={16} />
				<span>{backLabel}</span>
			</button>
		{/if}
		<PanelEmptyState
			title="ENTITY NOT FOUND"
			message="The requested fund data is unavailable in the current universe."
		/>
	</div>
{:else}
	<svelte:boundary>
		<div class="fs-container bg-[#222] text-white font-mono text-[11px] tabular-nums">
			<!-- ════════════ HEADER — BRUTALIST ════════════ -->
			<header class="bg-black p-4 border-b border-[#222]">
				{#if showBackButton && onBack}
					<button onclick={onBack} class="fs-back fs-no-print mb-4 p-0 text-[#71717a] hover:text-white flex items-center gap-2" type="button">
						<ArrowLeft size={14} />
						<span class="uppercase tracking-widest text-[10px] font-bold">{backLabel}</span>
					</button>
				{/if}

				<div class="grid grid-cols-[1fr_auto] gap-4 items-start">
					<div>
						<div class="flex items-center gap-2 mb-2">
							<span class="bg-[#222] text-[#71717a] px-1 py-0.5 text-[9px] font-black uppercase tracking-tighter">
								{UNIVERSE_LABELS[fund.universe as keyof typeof UNIVERSE_LABELS] ?? (fund.universe ?? "").toString().replace("_", " ").toUpperCase()}
							</span>
							{#if fund.manager_name}
								<span class="text-[10px] font-bold text-[#71717a] uppercase truncate max-w-[300px]">
									{fund.manager_name}
								</span>
							{/if}
						</div>
						<h1 class="text-2xl font-black leading-none tracking-tighter uppercase truncate">
							{fund.name}
						</h1>
					</div>

					<div class="flex flex-col items-end gap-1">
						{#if fund.ticker}
							<span class="text-2xl font-black text-(--ii-brand-primary) leading-none">
								{fund.ticker}
							</span>
						{/if}
						{#if asOfDate}
							<span class="text-[9px] text-[#71717a] uppercase font-bold">
								AS OF {formatDate(asOfDate, "short", "pt-BR")}
							</span>
						{/if}
						{#if onDownloadPdf}
							<button
								onclick={onDownloadPdf}
								disabled={pdfLoading}
								class="mt-2 bg-white text-black px-3 py-1 text-[10px] font-black uppercase tracking-widest hover:bg-(--ii-brand-primary) hover:text-white disabled:opacity-50"
							>
								{pdfLoading ? "EXPORTING..." : "EXPORT PDF"}
							</button>
						{/if}
					</div>
				</div>
			</header>

			<!-- ════════════ KPI GRID — 1PX GAP ════════════ -->
			<div class="grid grid-cols-2 md:grid-cols-6 gap-[1px] bg-[#222] border-b border-[#222]">
				<div class="bg-black p-3">
					<p class="text-[9px] text-[#71717a] font-black uppercase mb-1">NAV</p>
					<p class="text-lg font-black">{latestNav != null ? `$${formatNumber(latestNav, 2, "en-US", { useGrouping: false })}` : "—"}</p>
				</div>
				<div class="bg-black p-3">
					<p class="text-[9px] text-[#71717a] font-black uppercase mb-1">1D CHANGE</p>
					<p class="text-lg font-black {change1d != null && change1d >= 0 ? 'text-(--ii-success)' : 'text-(--ii-danger)'}">
						{change1d != null ? formatPercent(change1d) : "—"}
					</p>
				</div>
				<div class="bg-black p-3">
					<p class="text-[9px] text-[#71717a] font-black uppercase mb-1">NET ASSETS</p>
					<p class="text-lg font-black">{formatAum(fund.aum)}</p>
				</div>
				<div class="bg-black p-3">
					<p class="text-[9px] text-[#71717a] font-black uppercase mb-1">EXPENSE RATIO</p>
					<p class="text-lg font-black">{fund.expense_ratio_pct != null ? formatPercent(fund.expense_ratio_pct) : "—"}</p>
				</div>
				<div class="bg-black p-3 col-span-2">
					<p class="text-[9px] text-[#71717a] font-black uppercase mb-1">STRATEGY</p>
					<p class="text-xs font-black uppercase truncate">{fund.strategy_label || fund.fund_type || "—"}</p>
					<p class="text-[9px] text-[#71717a] uppercase mt-1">{fund.investment_geography || "GLOBAL"}</p>
				</div>
			</div>

			<div class="fs-body p-0 flex flex-col gap-[1px] bg-[#222]">
				<!-- INVESTMENT OBJECTIVE -->
				{#if strategy_narrative}
					<section class="bg-black p-4">
						<h3 class="text-[10px] font-black uppercase tracking-widest text-[#71717a] mb-2 border-b border-[#222] pb-1">
							INVESTMENT OBJECTIVE
						</h3>
						<p class="text-xs leading-tight text-[#d4d4d8] whitespace-pre-line font-medium">
							{strategy_narrative}
						</p>
					</section>
				{/if}

				<!-- MAIN CHARTS: PERFORMANCE + SCORING -->
				<div class="grid grid-cols-1 md:grid-cols-2 gap-[1px] bg-[#222]">
					<section class="bg-black p-3">
						<h3 class="text-[10px] font-black uppercase tracking-widest text-white mb-3">GROWTH OF $10,000</h3>
						<div class="h-[280px]">
							<NavPerformanceChart navData={nav_history} height={280} />
						</div>
					</section>
					<section class="bg-black p-3">
						<h3 class="text-[10px] font-black uppercase tracking-widest text-white mb-3">FUND ANALYSIS SCORE</h3>
						<div class="h-[280px]">
							<FundScoringRadar scoringMetrics={scoring_metrics} height={280} />
						</div>
					</section>
				</div>

				<!-- RAIO-X: TAIL RISK & EVESTMENT (PHASE 4.1) -->
				<div class="grid grid-cols-1 md:grid-cols-2 gap-[1px] bg-[#222]">
					<!-- TAIL RISK (GROUP 7) -->
					<section class="bg-black p-3">
						<h3 class="text-[10px] font-black uppercase tracking-widest text-(--ii-danger) mb-3 border-b border-[#222] pb-1">
							TAIL RISK (PHASE 4.1)
						</h3>
						<div class="grid grid-cols-3 gap-[1px] bg-[#222]">
							<div class="bg-black p-2">
								<p class="text-[9px] text-[#71717a] uppercase mb-1">VaR 95%</p>
								<p class="text-xs font-black">{analytics?.tail_risk?.var_parametric_95 != null ? formatPercent(analytics.tail_risk.var_parametric_95) : "—"}</p>
							</div>
							<div class="bg-black p-2">
								<p class="text-[9px] text-[#71717a] uppercase mb-1">CVaR 95%</p>
								<p class="text-xs font-black">{analytics?.tail_risk?.etl_95 != null ? formatPercent(analytics.tail_risk.etl_95) : "—"}</p>
							</div>
							<div class="bg-black p-2">
								<p class="text-[9px] text-[#71717a] uppercase mb-1">STARR RATIO</p>
								<p class="text-xs font-black">{analytics?.tail_risk?.starr_ratio != null ? formatNumber(analytics.tail_risk.starr_ratio, 2) : "—"}</p>
							</div>
							<div class="bg-black p-2">
								<p class="text-[9px] text-[#71717a] uppercase mb-1">RACHEV RATIO</p>
								<p class="text-xs font-black">{analytics?.tail_risk?.rachev_ratio != null ? formatNumber(analytics.tail_risk.rachev_ratio, 2) : "—"}</p>
							</div>
							<div class="bg-black p-2">
								<p class="text-[9px] text-[#71717a] uppercase mb-1">JARQUE-BERA P</p>
								<p class="text-xs font-black">{analytics?.tail_risk?.jarque_bera_pvalue != null ? formatNumber(analytics.tail_risk.jarque_bera_pvalue, 4) : "—"}</p>
							</div>
							<div class="bg-black p-2">
								<p class="text-[9px] text-[#71717a] uppercase mb-1">NORMALITY</p>
								<p class="text-xs font-black uppercase">{analytics?.tail_risk?.is_normal === true ? "PASS" : analytics?.tail_risk?.is_normal === false ? "FAIL" : "—"}</p>
							</div>
						</div>
					</section>

					<!-- EVESTMENT / PROFICIENCY (GROUP 6) -->
					<section class="bg-black p-3">
						<h3 class="text-[10px] font-black uppercase tracking-widest text-(--ii-brand-primary) mb-3 border-b border-[#222] pb-1">
							EVESTMENT STATISTICS
						</h3>
						<div class="grid grid-cols-2 gap-[1px] bg-[#222]">
							<div class="bg-black p-2">
								<p class="text-[9px] text-[#71717a] uppercase mb-1">DOWNSIDE DEV</p>
								<p class="text-xs font-black">{analytics?.return_statistics?.downside_deviation != null ? formatPercent(analytics.return_statistics.downside_deviation) : "—"}</p>
							</div>
							<div class="bg-black p-2">
								<p class="text-[9px] text-[#71717a] uppercase mb-1">SEMI-DEVIATION</p>
								<p class="text-xs font-black">{analytics?.return_statistics?.semi_deviation != null ? formatPercent(analytics.return_statistics.semi_deviation) : "—"}</p>
							</div>
							<div class="bg-black p-2">
								<p class="text-[9px] text-[#71717a] uppercase mb-1">UP PERC RATIO</p>
								<p class="text-xs font-black">{analytics?.return_statistics?.up_percentage_ratio != null ? formatPercent(analytics.return_statistics.up_percentage_ratio) : "—"}</p>
							</div>
							<div class="bg-black p-2">
								<p class="text-[9px] text-[#71717a] uppercase mb-1">GAIN/LOSS RATIO</p>
								<p class="text-xs font-black">{analytics?.return_statistics?.gain_loss_ratio != null ? formatNumber(analytics.return_statistics.gain_loss_ratio, 2) : "—"}</p>
							</div>
						</div>
					</section>
				</div>

				<!-- RAIO-X: DISTRIBUTION & ROLLING (PHASE 4.1 CHARTS) -->
				<div class="grid grid-cols-1 md:grid-cols-2 gap-[1px] bg-[#222]">
					<section class="bg-black p-3">
						<h3 class="text-[10px] font-black uppercase tracking-widest text-white mb-3">RETURN DISTRIBUTION</h3>
						<div class="h-[280px]">
							<ReturnDistributionChart 
								distribution={analytics?.distribution} 
								tailRisk={analytics?.tail_risk}
								height={280} 
							/>
						</div>
					</section>
					<section class="bg-black p-3">
						<h3 class="text-[10px] font-black uppercase tracking-widest text-white mb-3">ROLLING RETURNS</h3>
						<div class="h-[280px]">
							<RollingReturnsChart 
								rollingReturns={analytics?.rolling_returns} 
								height={280} 
							/>
						</div>
					</section>
				</div>

				<!-- HOLDINGS & ALLOCATION (REDUCED PADDING) -->
				<div class="grid grid-cols-1 md:grid-cols-2 gap-[1px] bg-[#222]">
					<section class="bg-black p-3">
						<h3 class="text-[10px] font-black uppercase tracking-widest text-white mb-3">SECTOR ALLOCATION</h3>
						<div class="h-[280px]">
							<SectorAllocationTreemap
								sectorWeights={sector_history[sector_history.length - 1]?.sector_weights}
								height={280}
							/>
						</div>
					</section>
					<section class="bg-black p-3">
						<h3 class="text-[10px] font-black uppercase tracking-widest text-white mb-3">TOP 10 HOLDINGS</h3>
						<div class="overflow-x-auto">
							<table class="w-full border-collapse text-[10px]">
								<thead>
									<tr class="bg-[#222]">
										<th class="text-left p-1 text-[#71717a] font-black uppercase">HOLDING</th>
										<th class="text-right p-1 text-[#71717a] font-black uppercase">WEIGHT</th>
									</tr>
								</thead>
								<tbody class="bg-black">
									{#each top_holdings.slice(0, 10) as h}
										<tr class="border-b border-[#222] hover:bg-[#111]">
											<td class="p-1 font-bold truncate max-w-[200px]">{h.name}</td>
											<td class="p-1 text-right font-black text-(--ii-brand-primary)">
												{formatPercent(h.pct_of_nav)}
											</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					</section>
				</div>

				<!-- ANNUAL RETURNS TABLE -->
				<section class="bg-black p-3">
					<h3 class="text-[10px] font-black uppercase tracking-widest text-white mb-3">ANNUALIZED PERFORMANCE</h3>
					<div class="overflow-x-auto">
						<table class="w-full border-collapse text-[10px]">
							<thead>
								<tr class="bg-[#222]">
									<th class="text-left p-1 text-[#71717a] font-black uppercase">PERIOD</th>
									<th class="text-right p-1 text-[#71717a] font-black uppercase">FUND</th>
									<th class="text-right p-1 text-[#71717a] font-black uppercase">+/&minus;</th>
								</tr>
							</thead>
							<tbody class="bg-black">
								{#each annual_returns as r}
									<tr class="border-b border-[#222] hover:bg-[#111]">
										<td class="p-1 font-bold">{r.year}</td>
										<td class="p-1 text-right font-black {r.annual_return_pct >= 0 ? 'text-(--ii-success)' : 'text-(--ii-danger)'}">
											{formatPercent(r.annual_return_pct)}
										</td>
										<td class="p-1 text-right text-[#71717a]">—</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				</section>
			</div>
		</div>

		{#snippet failed(error, reset)}
			<div class="fs-container p-4 bg-black border border-[#222]">
				<PanelErrorState
					title="RENDER FAILURE"
					message={error instanceof Error ? error.message : String(error)}
					onRetry={reset}
				/>
			</div>
		{/snippet}
	</svelte:boundary>
{/if}
