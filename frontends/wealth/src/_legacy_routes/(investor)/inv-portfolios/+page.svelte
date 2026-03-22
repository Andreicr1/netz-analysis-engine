<!--
  Investor — Model portfolios with track-record data (read-only).
  Institutional aesthetic: clean typography, controlled information density.
-->
<script lang="ts">
	import { DataCard, TimeSeriesChart, PageHeader, EmptyState, formatNumber, formatPercent, formatRatio, plColor } from "@netz/ui";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();

	type Portfolio = {
		id: string;
		profile: string;
		display_name: string;
		inception_nav: number;
		inception_date: string | null;
		benchmark_composite: string | null;
		trackRecord: {
			backtest: {
				equity_curve: [string, number][];
				annual_return: number | null;
				annual_volatility: number | null;
				sharpe_ratio: number | null;
				max_drawdown: number | null;
			} | null;
		} | null;
	};

	let portfolios = $derived((data.portfolios ?? []) as Portfolio[]);

	function fmtPct(v: number | null | undefined): string {
		return formatPercent(v, 2, "en-US", true);
	}

	function fmt(v: number | null | undefined, d = 2): string {
		return formatNumber(v, d, "en-US");
	}
</script>

<div class="mx-auto max-w-5xl space-y-8 p-6 md:p-10">
	<PageHeader title="Model Portfolios" />

	{#if portfolios.length === 0}
		<EmptyState
			title="No Portfolios Available"
			message="Model portfolio information will be available here once published."
		/>
	{:else}
		{#each portfolios as portfolio (portfolio.id)}
			<div class="rounded-lg border border-(--netz-border) bg-(--netz-surface-elevated) shadow-(--netz-shadow-1)">
				<!-- Header -->
				<div class="border-b border-(--netz-border) px-6 py-4">
					<h2 class="text-lg font-semibold text-(--netz-text-primary)">{portfolio.display_name}</h2>
					<p class="text-sm text-(--netz-text-muted) capitalize">
						{portfolio.profile}
						{#if portfolio.benchmark_composite}
							&middot; Benchmark: {portfolio.benchmark_composite}
						{/if}
					</p>
				</div>

				<!-- Metrics -->
				{#if portfolio.trackRecord?.backtest}
					{@const bt = portfolio.trackRecord.backtest}
					<div class="grid grid-cols-2 gap-4 border-b border-(--netz-border) px-6 py-4 md:grid-cols-4">
						<div>
							<p class="text-xs text-(--netz-text-muted)">Annual Return</p>
							<p class="text-lg font-semibold" style:color={plColor(bt.annual_return)}>
								{fmtPct(bt.annual_return)}
							</p>
						</div>
						<div>
							<p class="text-xs text-(--netz-text-muted)">Volatility</p>
							<p class="text-lg font-semibold text-(--netz-text-primary)">{fmtPct(bt.annual_volatility)}</p>
						</div>
						<div>
							<p class="text-xs text-(--netz-text-muted)">Sharpe Ratio</p>
							<p class="text-lg font-semibold text-(--netz-text-primary)">{formatRatio(bt.sharpe_ratio, 2, "", "en-US")}</p>
						</div>
						<div>
							<p class="text-xs text-(--netz-text-muted)">Max Drawdown</p>
							<p class="text-lg font-semibold text-(--netz-text-primary)">{fmtPct(bt.max_drawdown)}</p>
						</div>
					</div>

					<!-- Equity Curve -->
					{#if bt.equity_curve && bt.equity_curve.length > 0}
						<div class="px-6 py-4">
							<div class="h-64">
								<TimeSeriesChart
									series={[{ name: portfolio.display_name, data: bt.equity_curve }]}
									yAxisLabel="NAV"
									area={true}
									ariaLabel={`${portfolio.display_name} equity curve`}
								/>
							</div>
						</div>
					{/if}
				{:else}
					<div class="px-6 py-8">
						<p class="text-center text-sm text-(--netz-text-muted)">
							Track-record data not yet available for this portfolio.
						</p>
					</div>
				{/if}
			</div>
		{/each}
	{/if}
</div>
