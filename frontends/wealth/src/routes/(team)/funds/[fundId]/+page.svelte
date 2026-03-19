<!--
  Fund Detail — full metrics, NAV chart, risk metrics.
-->
<script lang="ts">
	import { DataCard, StatusBadge, TimeSeriesChart, PageHeader, EmptyState, formatDate, formatNumber, formatPercent, formatRatio } from "@netz/ui";
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

	type FundRisk = {
		cvar_95: number | null;
		var_95: number | null;
		annual_return: number | null;
		annual_volatility: number | null;
		sharpe_ratio: number | null;
		max_drawdown: number | null;
		recovery_days: number | null;
		sortino_ratio: number | null;
		calmar_ratio: number | null;
	};

	type NavPoint = {
		date: string;
		value: number;
	};

	let fund = $derived(data.fund as FundDetail | null);

	// Risk and NAV data will be provided by SSE-primary risk store (Sprint 1, Wealth.1).
	// Previous phantom API calls (/stats, /performance, /holdings) never returned data.
	let risk: FundRisk | null = null;
	let navHistory: NavPoint[] | null = null;

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

<div class="space-y-6 p-6">
	{#if fund}
		<PageHeader title={fund.name}>
			{#snippet actions()}
				<div class="flex items-center gap-2">
					{#if fund.ticker}
						<span class="rounded bg-[var(--netz-surface-alt)] px-2 py-1 text-xs font-mono text-[var(--netz-text-secondary)]">
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
		<div class="rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface-elevated)] p-5">
			<h3 class="mb-4 text-sm font-semibold text-[var(--netz-text-primary)]">NAV History</h3>
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
		</div>

		<!-- Risk Metrics -->
		{#if risk}
			<div class="rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface-elevated)] p-5">
				<h3 class="mb-4 text-sm font-semibold text-[var(--netz-text-primary)]">Risk Metrics</h3>
				<div class="grid gap-4 md:grid-cols-3 lg:grid-cols-5">
					<DataCard label="CVaR 95%" value={fmtPct(risk.cvar_95)} trend="flat" />
					<DataCard label="VaR 95%" value={fmtPct(risk.var_95)} trend="flat" />
					<DataCard label="Annual Return" value={fmtPct(risk.annual_return)} trend={risk.annual_return !== null && risk.annual_return >= 0 ? "up" : "down"} />
					<DataCard label="Volatility" value={fmtPct(risk.annual_volatility)} trend="flat" />
					<DataCard label="Sharpe" value={formatRatio(risk.sharpe_ratio, 2, "", "en-US")} trend="flat" />
					<DataCard label="Max Drawdown" value={fmtPct(risk.max_drawdown)} trend="flat" />
					<DataCard label="Recovery Days" value={risk.recovery_days !== null ? String(risk.recovery_days) : "—"} trend="flat" />
					<DataCard label="Sortino" value={formatRatio(risk.sortino_ratio, 2, "", "en-US")} trend="flat" />
					<DataCard label="Calmar" value={formatRatio(risk.calmar_ratio, 2, "", "en-US")} trend="flat" />
				</div>
			</div>
		{/if}
	{:else}
		<EmptyState title="Fund Not Found" message="The requested fund could not be loaded." />
	{/if}
</div>
