<!--
  Fund Detail — full metrics, NAV chart, risk metrics.
-->
<script lang="ts">
	import { DataCard, MetricCard, StatusBadge, TimeSeriesChart, PageHeader, SectionCard, EmptyState, formatDate, formatNumber, formatPercent, formatRatio } from "@netz/ui";
	import { resolveWealthStatus } from "$lib/utils/status-maps";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();

	type FundDetail = {
		id: string;
		name: string;
		ticker: string | null;
		block: string | null;
		geography: string | null;
		asset_class: string | null;
		manager_score: number | null;
		isin: string | null;
		cnpj: string | null;
		inception_date: string | null;
	};

	type FundRiskMetrics = {
		cvar_95_3m: number | null;
		var_95_3m: number | null;
		return_1y: number | null;
		volatility_1y: number | null;
		sharpe_1y: number | null;
		max_drawdown_1y: number | null;
		sortino_1y: number | null;
		rsi_14: number | null;
		bb_position: number | null;
		nav_momentum_score: number | null;
		flow_momentum_score: number | null;
		blended_momentum_score: number | null;
	};

	type NavPoint = {
		date: string;
		value: number;
	};

	let fund = $derived(data.fund as FundDetail | null);
	let riskMetrics = $derived(data.riskMetrics as FundRiskMetrics | null);

	// NAV data will be provided by SSE-primary risk store (Sprint 1, Wealth.1).
	let navHistory = $state<NavPoint[] | null>(null);

	function rsiStatus(rsi: number | null): "ok" | "warn" | "breach" | undefined {
		if (rsi == null) return undefined;
		if (rsi < 30) return "ok";
		if (rsi > 70) return "breach";
		return "warn";
	}

	// NAV chart series
	let navSeries = $derived(
		navHistory
			? [{ name: fund?.name ?? "NAV", data: navHistory.map((p: NavPoint) => [p.date, p.value] as [string, number]) }]
			: [],
	);

	function fmt(v: number | null, decimals = 2): string {
		return formatNumber(v, decimals, "en-US");
	}

	function fmtPct(v: number | null): string {
		return formatPercent(v, 2, "en-US");
	}
</script>

<div class="space-y-(--netz-space-section-gap) p-(--netz-space-page-gutter)">
	{#if fund}
		<PageHeader title={fund.name}>
			{#snippet actions()}
				<div class="flex items-center gap-2">
					{#if fund.ticker}
						<span class="rounded bg-(--netz-surface-alt) px-2 py-1 text-xs font-mono text-(--netz-text-secondary)">
							{fund.ticker}
						</span>
					{/if}
					{#if fund.block}
						<StatusBadge status={fund.block} resolve={resolveWealthStatus} />
					{/if}
				</div>
			{/snippet}
		</PageHeader>

		<!-- Fund Info -->
		<div class="grid gap-4 md:grid-cols-4">
			<DataCard label="Geography" value={fund.geography ?? "—"} trend="flat" />
			<DataCard label="Asset Class" value={fund.asset_class ?? "—"} trend="flat" />
			<DataCard label="Manager Score" value={fmt(fund.manager_score, 1)} trend="flat" />
			<DataCard label="Inception" value={formatDate(fund.inception_date)} trend="flat" />
		</div>

		<!-- NAV Chart -->
		<SectionCard title="NAV History">
			{#if navSeries.length > 0 && navSeries[0]!.data.length > 0}
				<div class="h-80">
					<TimeSeriesChart
						series={navSeries}
						yAxisLabel="NAV"
						area={true}
						ariaLabel={`${fund.name} NAV history`}
					/>
				</div>
			{:else}
				<EmptyState title="No NAV Data" message="NAV history will appear once ingested." />
			{/if}
		</SectionCard>

		<!-- Risk Metrics -->
		{#if riskMetrics}
			<SectionCard title="Risk Metrics">
				<div class="grid gap-4 md:grid-cols-3 lg:grid-cols-5">
					<DataCard label="CVaR 95% (3M)" value={fmtPct(riskMetrics.cvar_95_3m)} trend="flat" />
					<DataCard label="VaR 95% (3M)" value={fmtPct(riskMetrics.var_95_3m)} trend="flat" />
					<DataCard label="Return 1Y" value={fmtPct(riskMetrics.return_1y)} trend={riskMetrics.return_1y !== null && riskMetrics.return_1y >= 0 ? "up" : "down"} />
					<DataCard label="Volatility 1Y" value={fmtPct(riskMetrics.volatility_1y)} trend="flat" />
					<DataCard label="Sharpe 1Y" value={formatRatio(riskMetrics.sharpe_1y, 2, "", "en-US")} trend="flat" />
					<DataCard label="Max Drawdown 1Y" value={fmtPct(riskMetrics.max_drawdown_1y)} trend="flat" />
					<DataCard label="Sortino 1Y" value={formatRatio(riskMetrics.sortino_1y, 2, "", "en-US")} trend="flat" />
				</div>
			</SectionCard>

			<!-- Momentum Signals -->
			{#if riskMetrics.rsi_14 != null || riskMetrics.blended_momentum_score != null}
				<SectionCard title="Momentum Signals" subtitle="Deterministic Metric · Pre-computed by risk_calc worker">
					<div class="grid grid-cols-2 gap-3 md:grid-cols-5">
						<MetricCard label="RSI-14" value={riskMetrics.rsi_14 != null ? formatNumber(riskMetrics.rsi_14, 1, "en-US") : "—"} status={rsiStatus(riskMetrics.rsi_14)} sublabel={riskMetrics.rsi_14 != null ? (riskMetrics.rsi_14 < 30 ? "Oversold" : riskMetrics.rsi_14 > 70 ? "Overbought" : "Neutral") : "Pending"} />
						<MetricCard label="Bollinger" value={riskMetrics.bb_position != null ? formatNumber(riskMetrics.bb_position, 2, "en-US") : "—"} sublabel="Band position (0–1)" />
						<MetricCard label="NAV Momentum" value={riskMetrics.nav_momentum_score != null ? formatNumber(riskMetrics.nav_momentum_score, 2, "en-US") : "—"} />
						<MetricCard label="Flow Momentum" value={riskMetrics.flow_momentum_score != null ? formatNumber(riskMetrics.flow_momentum_score, 2, "en-US") : "—"} />
						<MetricCard label="Blended" value={riskMetrics.blended_momentum_score != null ? formatNumber(riskMetrics.blended_momentum_score, 2, "en-US") : "—"} sublabel="Composite score" />
					</div>
				</SectionCard>
			{/if}
		{:else}
			<SectionCard title="Risk Overview">
				<EmptyState title="No Risk Data" message="Risk metrics will appear after the risk_calc worker has run." />
			</SectionCard>
		{/if}
	{:else}
		<EmptyState title="Fund Not Found" message="The requested fund could not be loaded." />
	{/if}
</div>
