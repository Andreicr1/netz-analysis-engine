<!--
  Fund Fact Sheet — Executive Snapshot.
  Single-column hybrid layout: full-width header + KPIs,
  chart pairs in CSS Grid, institutional footer.
  Read-only view — analysis belongs in the Analytics tab.
-->
<script lang="ts">
	import { goto } from "$app/navigation";
	import { page as pageState } from "$app/state";
	import { ArrowLeft } from "lucide-svelte";
	import { formatCompact, formatPercent, formatDate } from "@investintell/ui";
	import { UNIVERSE_LABELS } from "$lib/types/catalog";
	import NavPerformanceChart from "$lib/components/charts/NavPerformanceChart.svelte";
	import SectorAllocationChart from "$lib/components/charts/SectorAllocationChart.svelte";
	import SectorAllocationTreemap from "$lib/components/charts/SectorAllocationTreemap.svelte";
	import FundScoringRadar from "$lib/components/charts/FundScoringRadar.svelte";
	import DecileBoxplot from "$lib/components/charts/DecileBoxplot.svelte";
	import "./factsheet.css";

	let { data } = $props();

	// ── Back navigation — return to L2 (manager fund list) if came from there ──
	const managerId = $derived(pageState.url.searchParams.get("manager"));
	const managerName = $derived(pageState.url.searchParams.get("manager_name"));

	function goBack() {
		if (managerId) {
			const params = new URLSearchParams({ manager: managerId });
			if (managerName) params.set("manager_name", managerName);
			goto(`/screener?${params.toString()}`);
		} else {
			goto("/screener");
		}
	}

	const factSheet = $derived(data.factSheet as Record<string, any>);
	const fund = $derived(factSheet.fund);
	const team = $derived(factSheet.team);
	const top_holdings = $derived(factSheet.top_holdings);
	const annual_returns = $derived(factSheet.annual_returns);
	const nav_history = $derived(factSheet.nav_history);
	const sector_history = $derived(factSheet.sector_history);
	const share_classes = $derived(factSheet.share_classes);
	const scoring_metrics = $derived(factSheet.scoring_metrics);
	const strategy_narrative = $derived(factSheet.strategy_narrative);
	const firm_description = $derived(factSheet.firm_description);
	const firm_website = $derived(factSheet.firm_website);

	// ── Derived KPI values ──
	const latestNav = $derived(nav_history?.at(-1)?.nav ?? null);
	const prevNav = $derived(nav_history?.at(-2)?.nav ?? null);
	const change1d = $derived(
		(latestNav != null && prevNav != null && prevNav !== 0)
			? (latestNav - prevNav) / prevNav
			: null
	);
	const asOfDate = $derived(nav_history?.at(-1)?.nav_date ?? null);

	function formatAum(val: number | null | undefined) {
		if (val == null) return "\u2014";
		return formatCompact(val);
	}

	function handlePrint() {
		window.print();
	}
</script>

<svelte:head>
	<title>{fund.name} | Fact Sheet</title>
</svelte:head>

<div class="fs-container w-full h-full rounded-2xl bg-[var(--ii-bg)] text-[var(--ii-text-primary)] font-[family-name:var(--ii-font-sans)] flex flex-col overflow-hidden">

	<!-- ════════════════════════════════════════════════════════
	     STICKY HEADER — Bloomberg-style (stays pinned)
	     ════════════════════════════════════════════════════════ -->
	<header class="flex-shrink-0 border-b-2 border-[var(--ii-border-subtle)] pb-6 px-4 md:px-6 pt-4 md:pt-6">
		<!-- Back button — L2 style -->
		<button onclick={goBack} class="fs-back fs-no-print">
			<ArrowLeft size={16} />
			<span>{managerId ? "Back to Fund List" : "Back to Managers"}</span>
		</button>

		<!-- Top row: manager + actions -->
		<div class="flex items-start justify-between mb-4">
			<div class="flex flex-col gap-1">
				<span class="inline-block px-2 py-0.5 bg-[var(--ii-surface-alt)] text-[var(--ii-text-muted)] text-[10px] font-bold rounded tracking-wider uppercase w-fit">
					{UNIVERSE_LABELS[fund.universe as keyof typeof UNIVERSE_LABELS] ?? fund.universe.replace("_", " ").toUpperCase()}
				</span>
				{#if fund.manager_name}
					<span class="text-sm font-semibold text-[var(--ii-text-muted)]">
						{fund.manager_name}
					</span>
				{/if}
			</div>

			<!-- Print / PDF actions -->
			<div class="flex items-center gap-2 fs-no-print">
				<button
					onclick={handlePrint}
					class="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg
					       border border-[var(--ii-border-subtle)] text-[var(--ii-text-secondary)]
					       hover:bg-[var(--ii-surface-alt)] transition-colors cursor-pointer"
				>
					<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
						<path d="M6 9V2h12v7M6 18H4a2 2 0 01-2-2v-5a2 2 0 012-2h16a2 2 0 012 2v5a2 2 0 01-2 2h-2"/>
						<rect x="6" y="14" width="12" height="8" rx="1"/>
					</svg>
					Print Fact Sheet
				</button>
				<button
					onclick={handlePrint}
					class="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg
					       bg-[var(--ii-brand-primary)] text-[var(--ii-text-inverse)]
					       hover:opacity-90 transition-opacity cursor-pointer"
				>
					<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
						<path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3"/>
					</svg>
					PDF
				</button>
			</div>
		</div>

		<!-- Main row: fund name + ticker -->
		<div class="flex items-end justify-between gap-6">
			<h1 class="text-xl md:text-2xl font-extrabold leading-tight tracking-tight text-[var(--ii-text-primary)] max-w-[70%]">
				{fund.name}
			</h1>
			<div class="flex flex-col items-end shrink-0">
				{#if fund.ticker}
					<span class="font-[family-name:var(--ii-font-mono)] text-xl md:text-2xl font-bold text-[var(--ii-brand-primary)] bg-[var(--ii-surface-accent)] px-3 py-1 rounded-lg">
						{fund.ticker}
					</span>
				{/if}
				{#if asOfDate}
					<span class="text-[11px] text-[var(--ii-text-muted)] mt-1">
						As of {formatDate(asOfDate)}
					</span>
				{/if}
			</div>
		</div>
	</header>

	<!-- ════════════════════════════════════════════════════════
	     SCROLLABLE BODY — everything below header scrolls
	     ════════════════════════════════════════════════════════ -->
	<div class="fs-body flex-1 min-h-0 overflow-y-auto p-4 md:p-6">

	<!-- ════════════════════════════════════════════════════════
	     KPI CARDS — full-width 5-column grid
	     ════════════════════════════════════════════════════════ -->
	<div class="grid grid-cols-2 md:grid-cols-5 gap-4 bg-[var(--ii-surface-alt)] p-5 rounded-xl border border-[var(--ii-border-subtle)] mb-8">
		<!-- NAV -->
		<div class="flex flex-col">
			<span class="text-[11px] font-semibold uppercase tracking-wider text-[var(--ii-text-muted)] mb-1">NAV</span>
			<span class="text-lg font-bold text-[var(--ii-text-primary)] fs-tabular">
				{latestNav != null ? `$${latestNav.toFixed(2)}` : "\u2014"}
			</span>
			<span class="text-[10px] text-[var(--ii-text-muted)]">Daily Value</span>
		</div>

		<!-- 1D Change -->
		<div class="flex flex-col">
			<span class="text-[11px] font-semibold uppercase tracking-wider text-[var(--ii-text-muted)] mb-1">1 Day Change</span>
			<span class="text-lg font-bold fs-tabular"
				class:text-[var(--ii-success)]={change1d != null && change1d >= 0}
				class:text-[var(--ii-danger)]={change1d != null && change1d < 0}
			>
				{change1d != null ? formatPercent(change1d) : "\u2014"}
			</span>
			{#if latestNav != null && prevNav != null}
				<span class="text-[10px] text-[var(--ii-text-muted)] fs-tabular">
					{change1d != null && change1d >= 0 ? "+" : ""}{(latestNav - prevNav).toFixed(2)}
				</span>
			{/if}
		</div>

		<!-- AUM -->
		<div class="flex flex-col">
			<span class="text-[11px] font-semibold uppercase tracking-wider text-[var(--ii-text-muted)] mb-1">Net Assets</span>
			<span class="text-lg font-bold text-[var(--ii-text-primary)] fs-tabular">
				{formatAum(fund.aum)}
			</span>
			<span class="text-[10px] text-[var(--ii-text-muted)]">Total Fund</span>
		</div>

		<!-- Expense Ratio -->
		<div class="flex flex-col">
			<span class="text-[11px] font-semibold uppercase tracking-wider text-[var(--ii-text-muted)] mb-1">Expense Ratio</span>
			<span class="text-lg font-bold text-[var(--ii-text-primary)] fs-tabular">
				{fund.expense_ratio_pct != null ? formatPercent(fund.expense_ratio_pct) : "\u2014"}
			</span>
			<span class="text-[10px] text-[var(--ii-text-muted)]">Gross</span>
		</div>

		<!-- Strategy -->
		<div class="flex flex-col col-span-2 md:col-span-1">
			<span class="text-[11px] font-semibold uppercase tracking-wider text-[var(--ii-text-muted)] mb-1">Strategy</span>
			<span class="text-sm font-bold text-[var(--ii-text-primary)] leading-snug">
				{fund.strategy_label || fund.fund_type || "\u2014"}
			</span>
			{#if fund.investment_geography}
				<span class="text-[10px] text-[var(--ii-text-muted)]">{fund.investment_geography}</span>
			{/if}
		</div>
	</div>

	<!-- ════════════════════════════════════════════════════════
	     INVESTMENT OBJECTIVE — promoted, accent panel
	     ════════════════════════════════════════════════════════ -->
	{#if strategy_narrative}
		<section class="rounded-xl bg-[var(--ii-surface-accent)] border border-[var(--ii-border-accent)] p-6 mb-8">
			<h3 class="text-xs font-semibold uppercase tracking-wider text-[var(--ii-text-muted)] mb-3">
				Investment Objective
			</h3>
			<p class="text-sm leading-relaxed text-[var(--ii-text-secondary)] whitespace-pre-line">
				{strategy_narrative}
			</p>
		</section>
	{/if}

	<!-- ════════════════════════════════════════════════════════
	     SCORING RADAR + PEER BOXPLOT — side-by-side
	     ════════════════════════════════════════════════════════ -->
	{#if scoring_metrics}
		<div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8 fs-grid-pair">
			<section class="fs-section">
				<h3 class="text-sm font-bold uppercase tracking-wider text-[var(--ii-text-primary)] border-l-4 border-[var(--ii-brand-primary)] pl-3 mb-5">
					Fund Analysis Score
				</h3>
				<div class="fs-chart-wrap">
					<FundScoringRadar scoringMetrics={scoring_metrics} height={300} />
				</div>
			</section>

			<section class="fs-section">
				<h3 class="text-sm font-bold uppercase tracking-wider text-[var(--ii-text-primary)] border-l-4 border-[var(--ii-brand-primary)] pl-3 mb-5">
					Peer Group Ranking
				</h3>
				<div class="fs-chart-wrap">
					{#if scoring_metrics.peer_percentiles}
						<DecileBoxplot
							percentiles={scoring_metrics.peer_percentiles}
							strategy={scoring_metrics.peer_strategy || fund.strategy_label || "Category"}
							height={300}
						/>
					{:else}
						<div class="flex items-center justify-center h-full text-sm italic text-[var(--ii-text-muted)]">
							Peer ranking not available.
						</div>
					{/if}
				</div>
			</section>
		</div>
	{/if}

	<!-- ════════════════════════════════════════════════════════
	     NAV PERFORMANCE — full-width (benchmark-ready)
	     ════════════════════════════════════════════════════════ -->
	{#if nav_history && nav_history.length > 0}
		<section class="fs-section mb-8">
			<h3 class="text-sm font-bold uppercase tracking-wider text-[var(--ii-text-primary)] border-l-4 border-[var(--ii-brand-primary)] pl-3 mb-5">
				Growth of $10,000
			</h3>
			<div class="fs-chart-wrap" style="height: 350px;">
				<NavPerformanceChart navData={nav_history} height={350} />
			</div>
		</section>
	{/if}

	<!-- ════════════════════════════════════════════════════════
	     SECTOR TREEMAP + SECTOR EVOLUTION — side-by-side
	     ════════════════════════════════════════════════════════ -->
	{#if sector_history && sector_history.length > 0}
		<div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8 fs-grid-pair">
			<section class="fs-section">
				<h3 class="text-sm font-bold uppercase tracking-wider text-[var(--ii-text-primary)] border-l-4 border-[var(--ii-brand-primary)] pl-3 mb-5">
					Sector Exposure
				</h3>
				<div class="fs-chart-wrap">
					<SectorAllocationTreemap
						sectorWeights={sector_history[sector_history.length - 1].sector_weights}
						height={300}
					/>
				</div>
			</section>

			<section class="fs-section">
				<h3 class="text-sm font-bold uppercase tracking-wider text-[var(--ii-text-primary)] border-l-4 border-[var(--ii-brand-primary)] pl-3 mb-5">
					Sector Evolution
				</h3>
				<div class="fs-chart-wrap">
					<SectorAllocationChart history={sector_history} height={300} />
				</div>
			</section>
		</div>
	{/if}

	<!-- ════════════════════════════════════════════════════════
	     AVERAGE ANNUALIZED RETURNS — with benchmark placeholders
	     ════════════════════════════════════════════════════════ -->
	{#if annual_returns.length > 0}
		<section class="fs-section mb-8">
			<h3 class="text-sm font-bold uppercase tracking-wider text-[var(--ii-text-primary)] border-l-4 border-[var(--ii-brand-primary)] pl-3 mb-5">
				Average Annualized Returns
			</h3>
			<div class="overflow-x-auto rounded-lg border border-[var(--ii-border-subtle)]">
				<table class="w-full border-collapse">
					<thead>
						<tr class="bg-[var(--ii-surface-alt)]">
							<th class="text-left text-[11px] font-semibold uppercase tracking-wider text-[var(--ii-text-muted)] px-4 py-3">
								Period
							</th>
							<th class="text-right text-[11px] font-semibold uppercase tracking-wider text-[var(--ii-text-muted)] px-4 py-3">
								Fund
							</th>
							<th class="text-right text-[11px] font-semibold uppercase tracking-wider text-[var(--ii-text-muted)] px-4 py-3">
								Benchmark
							</th>
							<th class="text-right text-[11px] font-semibold uppercase tracking-wider text-[var(--ii-text-muted)] px-4 py-3">
								+/&minus;
							</th>
						</tr>
					</thead>
					<tbody>
						{#each annual_returns as r}
							<tr class="border-t border-[var(--ii-border-subtle)] hover:bg-[var(--ii-surface-highlight)]">
								<td class="px-4 py-3 text-sm font-medium text-[var(--ii-text-primary)]">
									{r.year}
								</td>
								<td class="px-4 py-3 text-sm text-right font-bold fs-tabular"
									class:text-[var(--ii-success)]={r.annual_return_pct >= 0}
									class:text-[var(--ii-danger)]={r.annual_return_pct < 0}
								>
									{formatPercent(r.annual_return_pct)}
								</td>
								<td class="px-4 py-3 text-sm text-right text-[var(--ii-text-muted)] fs-tabular">
									&mdash;
								</td>
								<td class="px-4 py-3 text-sm text-right text-[var(--ii-text-muted)] fs-tabular">
									&mdash;
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</section>
	{/if}

	<!-- ════════════════════════════════════════════════════════
	     TOP 10 HOLDINGS — read-only, no interactivity
	     ════════════════════════════════════════════════════════ -->
	{#if top_holdings.length > 0}
		<section class="fs-section mb-8">
			<h3 class="text-sm font-bold uppercase tracking-wider text-[var(--ii-text-primary)] border-l-4 border-[var(--ii-brand-primary)] pl-3 mb-5">
				Top 10 Holdings
			</h3>
			<div class="overflow-x-auto rounded-lg border border-[var(--ii-border-subtle)]">
				<table class="w-full border-collapse">
					<thead>
						<tr class="bg-[var(--ii-surface-alt)]">
							<th class="text-left text-[11px] font-semibold uppercase tracking-wider text-[var(--ii-text-muted)] px-4 py-3">
								Holding
							</th>
							<th class="text-left text-[11px] font-semibold uppercase tracking-wider text-[var(--ii-text-muted)] px-4 py-3">
								Sector
							</th>
							<th class="text-right text-[11px] font-semibold uppercase tracking-wider text-[var(--ii-text-muted)] px-4 py-3">
								Weight
							</th>
						</tr>
					</thead>
					<tbody>
						{#each top_holdings.slice(0, 10) as h}
							<tr class="border-t border-[var(--ii-border-subtle)] hover:bg-[var(--ii-surface-highlight)]">
								<td class="px-4 py-2.5 text-sm font-semibold text-[var(--ii-text-primary)]">
									{h.name}
								</td>
								<td class="px-4 py-2.5 text-xs text-[var(--ii-text-muted)]">
									{h.sector || "Other"}
								</td>
								<td class="px-4 py-2.5 text-sm text-right font-bold text-[var(--ii-text-primary)] fs-tabular">
									{formatPercent(h.pct_of_nav)}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</section>
	{/if}

	<!-- ════════════════════════════════════════════════════════
	     SHARE CLASSES
	     ════════════════════════════════════════════════════════ -->
	{#if share_classes.length > 0}
		<section class="fs-section mb-8">
			<h3 class="text-sm font-bold uppercase tracking-wider text-[var(--ii-text-primary)] border-l-4 border-[var(--ii-brand-primary)] pl-3 mb-5">
				Share Classes
			</h3>
			<div class="overflow-x-auto rounded-lg border border-[var(--ii-border-subtle)]">
				<table class="w-full border-collapse">
					<thead>
						<tr class="bg-[var(--ii-surface-alt)]">
							<th class="text-left text-[11px] font-semibold uppercase tracking-wider text-[var(--ii-text-muted)] px-4 py-3">Class</th>
							<th class="text-left text-[11px] font-semibold uppercase tracking-wider text-[var(--ii-text-muted)] px-4 py-3">Ticker</th>
							<th class="text-right text-[11px] font-semibold uppercase tracking-wider text-[var(--ii-text-muted)] px-4 py-3">ER%</th>
							<th class="text-right text-[11px] font-semibold uppercase tracking-wider text-[var(--ii-text-muted)] px-4 py-3">1Y Ret</th>
							<th class="text-right text-[11px] font-semibold uppercase tracking-wider text-[var(--ii-text-muted)] px-4 py-3">Net Assets</th>
						</tr>
					</thead>
					<tbody>
						{#each share_classes as sc}
							<tr class="border-t border-[var(--ii-border-subtle)] hover:bg-[var(--ii-surface-highlight)]">
								<td class="px-4 py-2.5 text-sm text-[var(--ii-text-primary)]">{sc.class_name || sc.series_name || sc.class_id || "Primary"}</td>
								<td class="px-4 py-2.5">
									<code class="text-xs font-[family-name:var(--ii-font-mono)] bg-[var(--ii-surface-alt)] px-1.5 py-0.5 rounded text-[var(--ii-text-primary)]">
										{sc.ticker || "\u2014"}
									</code>
								</td>
								<td class="px-4 py-2.5 text-sm text-right fs-tabular text-[var(--ii-text-primary)]">
									{sc.expense_ratio_pct != null ? formatPercent(sc.expense_ratio_pct) : "\u2014"}
								</td>
								<td class="px-4 py-2.5 text-sm text-right fs-tabular"
									class:text-[var(--ii-success)]={sc.avg_annual_return_pct != null && sc.avg_annual_return_pct >= 0}
									class:text-[var(--ii-danger)]={sc.avg_annual_return_pct != null && sc.avg_annual_return_pct < 0}
								>
									{sc.avg_annual_return_pct != null ? formatPercent(sc.avg_annual_return_pct) : "\u2014"}
								</td>
								<td class="px-4 py-2.5 text-sm text-right fs-tabular text-[var(--ii-text-primary)]">
									{formatAum(sc.net_assets)}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</section>
	{/if}

	<!-- ════════════════════════════════════════════════════════
	     INSTITUTIONAL FOOTER — Firm + Team side-by-side
	     ════════════════════════════════════════════════════════ -->
	{#if firm_description || firm_website || team.length > 0}
		<div class="border-t border-[var(--ii-border-subtle)] pt-8 mt-8">
			<div class="grid grid-cols-1 md:grid-cols-2 gap-8">
				<!-- Firm Overview -->
				{#if firm_description || firm_website}
					<section>
						<h3 class="text-sm font-bold uppercase tracking-wider text-[var(--ii-text-primary)] border-l-4 border-[var(--ii-brand-primary)] pl-3 mb-5">
							About the Firm
						</h3>
						<div class="p-4 bg-[var(--ii-surface-alt)] border border-[var(--ii-border-subtle)] rounded-xl">
							{#if firm_description}
								<p class="text-[13px] leading-relaxed text-[var(--ii-text-secondary)] whitespace-pre-line">
									{firm_description}
								</p>
							{/if}
							{#if firm_website}
								<a
									href={firm_website.startsWith("http") ? firm_website : `https://${firm_website}`}
									target="_blank"
									rel="noopener noreferrer"
									class="inline-block mt-3 text-xs font-semibold text-[var(--ii-brand-primary)] hover:underline"
								>
									{firm_website}
								</a>
							{/if}
						</div>
					</section>
				{/if}

				<!-- Management Team -->
				{#if team.length > 0}
					<section>
						<h3 class="text-sm font-bold uppercase tracking-wider text-[var(--ii-text-primary)] border-l-4 border-[var(--ii-brand-primary)] pl-3 mb-5">
							Management Team
						</h3>
						<div class="flex flex-col gap-3">
							{#each team as member}
								<div class="p-4 bg-[var(--ii-surface-alt)] border border-[var(--ii-border-subtle)] rounded-xl">
									<div class="text-sm font-bold text-[var(--ii-text-primary)]">{member.person_name}</div>
									<div class="text-xs font-semibold text-[var(--ii-brand-primary)] mb-1">
										{member.title || member.role || "Portfolio Manager"}
									</div>
									{#if member.bio_summary}
										<p class="text-xs leading-relaxed text-[var(--ii-text-muted)] mt-1">
											{member.bio_summary}
										</p>
									{/if}
									{#if member.education || (member.certifications && member.certifications.length > 0)}
										<div class="text-[11px] italic text-[var(--ii-text-muted)] mt-1">
											{member.education || ""}
											{member.certifications?.join(", ") || ""}
										</div>
									{/if}
								</div>
							{/each}
						</div>
					</section>
				{/if}
			</div>
		</div>
	{/if}

	</div><!-- /fs-body -->
</div>
