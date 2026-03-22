<!--
  Model Portfolio Detail — composition, track record, backtest + stress results.
-->
<script lang="ts">
	import { DataCard, StatusBadge, TimeSeriesChart, BarChart, PageHeader, SectionCard, EmptyState, formatDate, formatNumber, formatPercent, formatRatio } from "@netz/ui";
	import { resolveWealthStatus } from "$lib/utils/status-maps";
	import type { PageData } from "./$types";

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
		fund_selection_schema: Record<string, unknown> | null;
	};

	type TrackRecord = {
		backtest: {
			equity_curve: [string, number][];
			annual_return: number | null;
			annual_volatility: number | null;
			sharpe_ratio: number | null;
			max_drawdown: number | null;
		} | null;
		stress: {
			scenarios: { name: string; impact: number }[];
		} | null;
	};

	let portfolio = $derived(data.portfolio as ModelPortfolio | null);
	let trackRecord = $derived(data.trackRecord as TrackRecord | null);

	// Chart data
	let equityCurveSeries = $derived(
		trackRecord?.backtest?.equity_curve
			? [{ name: portfolio?.display_name ?? "Portfolio", data: trackRecord.backtest.equity_curve }]
			: [],
	);

	let stressData = $derived(
		trackRecord?.stress?.scenarios?.map((s) => ({ name: s.name, value: s.impact * 100 })) ?? [],
	);

	function fmt(v: number | null | undefined, decimals = 2): string {
		return formatNumber(v, decimals, "en-US");
	}

	function fmtPct(v: number | null | undefined): string {
		return formatPercent(v, 2, "en-US");
	}
</script>

<div class="space-y-(--netz-space-section-gap) p-(--netz-space-page-gutter)">
	{#if portfolio}
		<PageHeader title={portfolio.display_name}>
			{#snippet actions()}
				<div class="flex items-center gap-2">
					<StatusBadge status={portfolio.status} resolve={resolveWealthStatus} />
					<span class="text-sm text-(--netz-text-muted) capitalize">{portfolio.profile}</span>
				</div>
			{/snippet}
		</PageHeader>

		<!-- Portfolio Info -->
		<div class="grid gap-4 md:grid-cols-4">
			<DataCard label="Profile" value={portfolio.profile} trend="flat" />
			<DataCard label="Benchmark" value={portfolio.benchmark_composite ?? "—"} trend="flat" />
			<DataCard label="Inception" value={formatDate(portfolio.inception_date)} trend="flat" />
			<DataCard label="Inception NAV" value={formatNumber(portfolio.inception_nav, 2, "en-US")} trend="flat" />
		</div>

		{#if portfolio.description}
			<SectionCard title="Description">
				<p class="text-sm text-(--netz-text-secondary)">{portfolio.description}</p>
			</SectionCard>
		{/if}

		<!-- Backtest Equity Curve -->
		<SectionCard title="Backtest Equity Curve">
			{#if equityCurveSeries.length > 0 && equityCurveSeries[0]!.data.length > 0}
				<div class="h-80">
					<TimeSeriesChart
						series={equityCurveSeries}
						yAxisLabel="NAV"
						area={true}
						ariaLabel={`${portfolio.display_name} backtest equity curve`}
					/>
				</div>
			{:else}
				<EmptyState title="No Backtest Data" message="Run a backtest to see the equity curve." />
			{/if}
		</SectionCard>

		<!-- Backtest Metrics -->
		{#if trackRecord?.backtest}
			<div class="grid gap-4 md:grid-cols-4">
				<DataCard label="Annual Return" value={fmtPct(trackRecord.backtest.annual_return)} trend={trackRecord.backtest.annual_return != null && trackRecord.backtest.annual_return >= 0 ? "up" : "down"} />
				<DataCard label="Volatility" value={fmtPct(trackRecord.backtest.annual_volatility)} trend="flat" />
				<DataCard label="Sharpe" value={formatRatio(trackRecord.backtest.sharpe_ratio, 2, "", "en-US")} trend="flat" />
				<DataCard label="Max Drawdown" value={fmtPct(trackRecord.backtest.max_drawdown)} trend="flat" />
			</div>
		{/if}

		<!-- Stress Scenarios -->
		{#if stressData.length > 0}
			<SectionCard title="Stress Scenarios">
				<div class="h-64">
					<BarChart
						data={stressData}
						orientation="horizontal"
					/>
				</div>
			</SectionCard>
		{/if}
	{:else}
		<EmptyState title="Portfolio Not Found" message="The requested model portfolio could not be loaded." />
	{/if}
</div>
