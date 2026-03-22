<!--
  Market Data — Credit market indicators from macro_data hypertable.
  Sections: Credit Spreads, Yield Curve, Case-Shiller, Housing & Banking.
-->
<script lang="ts">
	import {
		PageHeader,
		SectionCard,
		MetricCard,
		EmptyState,
		formatNumber,
	} from "@netz/ui";
	import { TimeSeriesChart } from "@netz/ui/charts";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();

	// ── Types ──

	interface SeriesPoint {
		date: string;
		value: number;
	}

	interface SeriesData {
		label: string;
		points: SeriesPoint[];
		latest: number | null;
	}

	interface MarketDataResponse {
		sections: Record<string, Record<string, SeriesData>>;
		yieldCurveSnapshot: Array<{
			seriesId: string;
			label: string;
			value: number;
			date: string;
		}>;
		spread2s10s: number | null;
		inverted: boolean;
		asOfDate: string;
		source: string;
	}

	let md = $derived(data.marketData as MarketDataResponse | null);
	let sections = $derived(md?.sections ?? {});

	// ── Helpers ──

	function toChartSeries(
		sectionKey: string,
		seriesIds: string[],
	): { name: string; data: [string, number][] }[] {
		const section = sections[sectionKey] ?? {};
		return seriesIds
			.filter((sid) => section[sid]?.points?.length)
			.map((sid) => ({
				name: section[sid].label,
				data: section[sid].points.map((p: SeriesPoint) => [p.date, p.value] as [string, number]),
			}));
	}

	function latestValue(sectionKey: string, seriesId: string): number | null {
		return sections[sectionKey]?.[seriesId]?.latest ?? null;
	}

	function fmtRate(v: number | null): string {
		if (v == null) return "--";
		return formatNumber(v, 2) + "%";
	}

	function fmtIndex(v: number | null): string {
		if (v == null) return "--";
		return formatNumber(v, 1);
	}

	function fmtBps(v: number | null): string {
		if (v == null) return "--";
		return formatNumber(v * 100, 0) + " bps";
	}

	// ── Credit Spreads ──
	let spreadSeries = $derived(toChartSeries("credit_spreads", ["BAA10Y", "BAMLH0A0HYM2"]));

	// ── Yield Curve ──
	let yieldSeries = $derived(toChartSeries("yield_curve", ["DFF", "SOFR", "DGS2", "DGS10"]));

	// ── Case-Shiller ──
	let caseShillerNational = $derived(
		toChartSeries("case_shiller_national", ["CSUSHPINSA"]),
	);

	// Metro options
	const METRO_OPTIONS: { id: string; label: string }[] = [
		{ id: "NYXRSA", label: "New York" },
		{ id: "LXXRSA", label: "Los Angeles" },
		{ id: "MFHXRSA", label: "Miami" },
		{ id: "CHXRSA", label: "Chicago" },
		{ id: "DAXRSA", label: "Dallas" },
		{ id: "HIOXRSA", label: "Houston" },
		{ id: "WDXRSA", label: "Washington DC" },
		{ id: "BOXRSA", label: "Boston" },
		{ id: "ATXRSA", label: "Atlanta" },
		{ id: "SEXRSA", label: "Seattle" },
		{ id: "PHXRSA", label: "Phoenix" },
		{ id: "DNXRSA", label: "Denver" },
		{ id: "SFXRSA", label: "San Francisco" },
		{ id: "TPXRSA", label: "Tampa" },
		{ id: "CRXRSA", label: "Charlotte" },
		{ id: "MNXRSA", label: "Minneapolis" },
		{ id: "POXRSA", label: "Portland" },
		{ id: "SDXRSA", label: "San Diego" },
		{ id: "DEXRSA", label: "Detroit" },
		{ id: "CLXRSA", label: "Cleveland" },
	];

	let selectedMetros = $state<string[]>(["NYXRSA", "LXXRSA", "MFHXRSA"]);

	let metroSeries = $derived(toChartSeries("case_shiller_metro", selectedMetros));

	function toggleMetro(metroId: string) {
		if (selectedMetros.includes(metroId)) {
			selectedMetros = selectedMetros.filter((m) => m !== metroId);
		} else if (selectedMetros.length < 5) {
			selectedMetros = [...selectedMetros, metroId];
		}
	}

	// ── Housing metrics ──
	let mortgageSeries = $derived(toChartSeries("mortgage", ["MORTGAGE30US", "MORTGAGE15US"]));

	// ── Delinquency & Credit Quality ──
	let delinquencySeries = $derived(
		toChartSeries("delinquency", ["DRCCLACBS", "DRSFRMACBS", "DRHMACBS"]),
	);
	let creditQualitySeries = $derived(
		toChartSeries("credit_quality", ["DRALACBN", "NETCIBAL", "DRCILNFNQ"]),
	);

	// ── Banking ──
	let stressSeries = $derived(toChartSeries("banking", ["STLFSI4"]));
</script>

<PageHeader
	title="Market Data"
	subtitle="Credit market indicators from FRED — deterministic, DB-sourced"
/>

{#if !md}
	<EmptyState message="Market data unavailable. Macro ingestion worker may not have run yet." />
{:else}
	<!-- Provenance banner -->
	<div class="mb-6 flex items-center gap-2 rounded-(--netz-radius-md) border border-(--netz-border-subtle) bg-(--netz-surface-highlight) px-4 py-2 text-xs text-(--netz-text-muted)">
		<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="shrink-0">
			<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>
		</svg>
		<span>Source: {md.source} &mdash; Deterministic Metric &mdash; As of {md.asOfDate}</span>
	</div>

	<div class="space-y-6">
		<!-- ── Section 1: Credit Spreads ── -->
		<SectionCard title="Credit Spreads" subtitle="BAA OAS & High Yield">
			<div class="grid grid-cols-1 gap-4 sm:grid-cols-3">
				<MetricCard
					label="Baa Corporate Spread"
					value={fmtRate(latestValue("credit_spreads", "BAA10Y"))}
				/>
				<MetricCard
					label="HY OAS Spread"
					value={fmtRate(latestValue("credit_spreads", "BAMLH0A0HYM2"))}
				/>
				<MetricCard
					label="2s10s Spread"
					value={md.spread2s10s != null ? fmtBps(md.spread2s10s) : "--"}
					status={md.inverted ? "warn" : "ok"}
					sublabel={md.inverted ? "Curve Inverted" : "Normal"}
				/>
			</div>
			{#if spreadSeries.length}
				<div class="mt-4">
					<TimeSeriesChart
						series={spreadSeries}
						yAxisLabel="Spread (%)"
						height={320}
						ariaLabel="Credit spreads over time"
					/>
				</div>
			{/if}
		</SectionCard>

		<!-- ── Section 2: Yield Curve ── -->
		<SectionCard title="Yield Curve" subtitle="Key rates & inversion indicator">
			{#if md.yieldCurveSnapshot.length}
				<div class="grid grid-cols-2 gap-4 sm:grid-cols-4">
					{#each md.yieldCurveSnapshot as point (point.label)}
						<MetricCard
							label={point.label}
							value={fmtRate(point.value)}
							sublabel={point.date}
						/>
					{/each}
				</div>
			{/if}
			{#if yieldSeries.length}
				<div class="mt-4">
					<TimeSeriesChart
						series={yieldSeries}
						yAxisLabel="Rate (%)"
						height={320}
						ariaLabel="Yield curve rates over time"
					/>
				</div>
			{/if}
		</SectionCard>

		<!-- ── Section 3: Case-Shiller ── -->
		<SectionCard title="Case-Shiller Home Price Index" subtitle="National & metro-level">
			{#if caseShillerNational.length}
				<div class="mb-4">
					<MetricCard
						label="National HPI"
						value={fmtIndex(latestValue("case_shiller_national", "CSUSHPINSA"))}
					/>
				</div>
				<TimeSeriesChart
					series={caseShillerNational}
					yAxisLabel="Index"
					height={280}
					ariaLabel="Case-Shiller National Home Price Index"
				/>
			{/if}

			<!-- Metro selector -->
			<div class="mt-6">
				<p class="mb-2 text-xs font-semibold uppercase tracking-wide text-(--netz-text-muted)">
					Metro Areas (select up to 5)
				</p>
				<div class="flex flex-wrap gap-2">
					{#each METRO_OPTIONS as metro (metro.id)}
						<button
							type="button"
							class="rounded-full border px-3 py-1 text-xs font-medium transition-colors
								{selectedMetros.includes(metro.id)
									? 'border-(--netz-brand-secondary) bg-(--netz-brand-secondary)/10 text-(--netz-brand-secondary)'
									: 'border-(--netz-border-subtle) text-(--netz-text-secondary) hover:border-(--netz-brand-secondary)/50'}"
							onclick={() => toggleMetro(metro.id)}
							disabled={!selectedMetros.includes(metro.id) && selectedMetros.length >= 5}
						>
							{metro.label}
						</button>
					{/each}
				</div>
				{#if metroSeries.length}
					<div class="mt-4">
						<TimeSeriesChart
							series={metroSeries}
							yAxisLabel="Index"
							height={320}
							ariaLabel="Case-Shiller Metro Home Price Indexes"
						/>
					</div>
				{:else}
					<p class="mt-4 text-sm text-(--netz-text-muted)">
						No metro data available for selected cities.
					</p>
				{/if}
			</div>
		</SectionCard>

		<!-- ── Section 4: Housing & Mortgage ── -->
		<SectionCard title="Housing & Mortgage" subtitle="Starts, permits, sales, mortgage rates">
			<div class="grid grid-cols-2 gap-4 sm:grid-cols-5">
				<MetricCard
					label="Median Sale Price"
					value={latestValue("housing", "MSPUS") != null
						? "$" + formatNumber(latestValue("housing", "MSPUS")!, 0)
						: "--"}
				/>
				<MetricCard
					label="Housing Starts"
					value={fmtIndex(latestValue("housing", "HOUST"))}
					sublabel="SAAR (000s)"
				/>
				<MetricCard
					label="Building Permits"
					value={fmtIndex(latestValue("housing", "PERMIT"))}
					sublabel="SAAR (000s)"
				/>
				<MetricCard
					label="Existing Sales"
					value={fmtIndex(latestValue("housing", "EXHOSLUSM495S"))}
					sublabel="SAAR (M)"
				/>
				<MetricCard
					label="Months Supply"
					value={fmtIndex(latestValue("housing", "MSACSR"))}
				/>
			</div>
			{#if mortgageSeries.length}
				<div class="mt-4">
					<TimeSeriesChart
						series={mortgageSeries}
						yAxisLabel="Rate (%)"
						height={280}
						ariaLabel="Mortgage rates over time"
					/>
				</div>
			{/if}
		</SectionCard>

		<!-- ── Section 5: Credit Quality & Delinquency ── -->
		<SectionCard title="Credit Quality & Delinquency" subtitle="Banking system health">
			<div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
				{#if delinquencySeries.length}
					<div>
						<p class="mb-2 text-xs font-semibold uppercase tracking-wide text-(--netz-text-muted)">
							Delinquency Rates
						</p>
						<TimeSeriesChart
							series={delinquencySeries}
							yAxisLabel="Rate (%)"
							height={280}
							ariaLabel="Delinquency rates over time"
						/>
					</div>
				{/if}
				{#if creditQualitySeries.length}
					<div>
						<p class="mb-2 text-xs font-semibold uppercase tracking-wide text-(--netz-text-muted)">
							Credit Quality
						</p>
						<TimeSeriesChart
							series={creditQualitySeries}
							yAxisLabel="Rate (%)"
							height={280}
							ariaLabel="Credit quality metrics over time"
						/>
					</div>
				{/if}
			</div>
		</SectionCard>

		<!-- ── Section 6: Financial Stress ── -->
		<SectionCard title="Financial Stress" subtitle="St. Louis Fed Financial Stress Index">
			<div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
				<MetricCard
					label="STLFSI4"
					value={fmtIndex(latestValue("banking", "STLFSI4"))}
					sublabel="0 = normal conditions"
					status={(() => {
						const v = latestValue("banking", "STLFSI4");
						if (v == null) return undefined;
						if (v > 1.0) return "breach" as const;
						if (v > 0.5) return "warn" as const;
						return "ok" as const;
					})()}
				/>
			</div>
			{#if stressSeries.length}
				<div class="mt-4">
					<TimeSeriesChart
						series={stressSeries}
						yAxisLabel="Index"
						height={280}
						area={true}
						ariaLabel="Financial Stress Index over time"
					/>
				</div>
			{/if}
		</SectionCard>
	</div>
{/if}
