<!--
  Fund Fact Sheet — L2→L3: rich detail page with Overview, Holdings, Style, Team tabs.
  Holdings loaded lazily on tab activation. Style + Team use SSR data.
-->
<script lang="ts">
	import { goto } from "$app/navigation";
	import { getContext } from "svelte";
	import {
		AlertBanner,
		EmptyState,
		Skeleton,
		StatusBadge,
		formatAUM,
		formatPercent,
		formatNumber,
	} from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import type { PageData } from "./$types";
	import type { NportHoldingsPage, NportHoldingItem } from "$lib/types/sec-funds";
	import { EMPTY_HOLDINGS } from "$lib/types/sec-funds";

	let { data }: { data: PageData } = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

	let fund = $derived(data.fund);
	let styleHistory = $derived(data.styleHistory);
	let activeTab = $state<"overview" | "holdings" | "style" | "team">("overview");

	// ── Holdings lazy fetch ──
	let holdingsData = $state<NportHoldingsPage>(EMPTY_HOLDINGS);
	let holdingsLoading = $state(false);
	let selectedQuarter = $state<string | undefined>(undefined);

	$effect(() => {
		if (activeTab !== "holdings" || !fund) return;
		const controller = new AbortController();
		holdingsLoading = true;

		const params: Record<string, string> = {};
		if (selectedQuarter !== undefined) params.quarter = selectedQuarter;

		api
			.get<NportHoldingsPage>(`/sec/funds/${data.cik}/holdings`, params)
			.then((res) => {
				if (!controller.signal.aborted) {
					holdingsData = res;
					if (selectedQuarter === undefined && res.available_quarters.length > 0) {
						selectedQuarter = res.available_quarters[0];
					}
				}
			})
			.catch(() => {
				if (!controller.signal.aborted) holdingsData = EMPTY_HOLDINGS;
			})
			.finally(() => {
				if (!controller.signal.aborted) holdingsLoading = false;
			});

		return () => controller.abort();
	});

	// ── Style helpers ──
	const STYLE_COLORS: Record<string, string> = {
		large_growth: "bg-emerald-100 text-emerald-800",
		large_blend: "bg-blue-100 text-blue-800",
		large_value: "bg-amber-100 text-amber-800",
		mid_growth: "bg-emerald-50 text-emerald-700",
		mid_blend: "bg-blue-50 text-blue-700",
		mid_value: "bg-amber-50 text-amber-700",
		small_growth: "bg-teal-100 text-teal-800",
		small_blend: "bg-slate-100 text-slate-700",
		small_value: "bg-orange-100 text-orange-800",
		fixed_income: "bg-violet-100 text-violet-800",
		mixed: "bg-gray-100 text-gray-700",
		unknown: "bg-gray-50 text-gray-500",
	};

	function styleLabel(label: string): string {
		return label.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
	}

	function sortedSectorWeights(
		weights: Record<string, number>,
	): [string, number][] {
		return Object.entries(weights).sort((a, b) => b[1] - a[1]);
	}
</script>

<div class="space-y-6">
	<!-- Back link -->
	<button
		class="text-sm text-(--netz-muted) hover:text-(--netz-fg) transition-colors"
		onclick={() => goto(`/us-fund-analysis/${data.crd}`)}
	>
		&larr; Back to {fund?.firm?.firm_name ?? "Manager"}
	</button>

	{#if !fund}
		<EmptyState title="Fund not found" message="No data available for this fund." />
	{:else}
		<!-- Header -->
		<div class="border border-(--netz-border) rounded-lg p-6 bg-(--netz-surface)">
			<h1 class="text-xl font-semibold text-(--netz-fg)">{fund.fund_name}</h1>
			<div class="mt-2 flex flex-wrap items-center gap-3 text-sm text-(--netz-muted)">
				<span class="inline-flex items-center rounded px-2 py-0.5 text-xs font-medium bg-(--netz-surface-raised)">
					{fund.fund_type.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
				</span>
				<span>{fund.domicile}</span>
				<span>{fund.currency}</span>
				{#if fund.total_assets}
					<span>AUM {formatAUM(fund.total_assets)}</span>
				{/if}
				{#if fund.ticker}
					<span class="font-mono">{fund.ticker}</span>
				{/if}
				{#if fund.isin}
					<span class="font-mono text-xs">{fund.isin}</span>
				{/if}
			</div>

			{#if !fund.data_availability.has_holdings && fund.data_availability.disclosure_note}
				<div class="mt-4">
					<AlertBanner variant="info">{fund.data_availability.disclosure_note}</AlertBanner>
				</div>
			{/if}
		</div>

		<!-- Tabs -->
		<div class="border-b border-(--netz-border)">
			<nav class="flex gap-6">
				{#each [
					{ id: "overview", label: "Overview" },
					{ id: "holdings", label: "Holdings" },
					{ id: "style", label: "Style" },
					{ id: "team", label: "Team" },
				] as tab (tab.id)}
					<button
						class="pb-2 text-sm font-medium transition-colors {activeTab === tab.id
							? 'border-b-2 border-(--netz-accent) text-(--netz-fg)'
							: 'text-(--netz-muted) hover:text-(--netz-fg)'}"
						onclick={() => (activeTab = tab.id as typeof activeTab)}
					>
						{tab.label}
					</button>
				{/each}
			</nav>
		</div>

		<!-- Tab: Overview -->
		{#if activeTab === "overview"}
			<div class="grid grid-cols-1 md:grid-cols-3 gap-6">
				<!-- Strategy card -->
				<div class="border border-(--netz-border) rounded-lg p-4 bg-(--netz-surface)">
					<h3 class="text-sm font-medium text-(--netz-muted) mb-3">Strategy</h3>
					{#if fund.latest_style}
						<div class="mb-3">
							<span class="inline-flex items-center rounded px-2 py-1 text-sm font-medium {STYLE_COLORS[fund.latest_style.style_label] ?? STYLE_COLORS.unknown}">
								{styleLabel(fund.latest_style.style_label)}
							</span>
						</div>
						<div class="space-y-1.5">
							{#each sortedSectorWeights(fund.latest_style.sector_weights).slice(0, 5) as [sector, weight]}
								<div class="flex justify-between text-sm">
									<span class="text-(--netz-fg)">{sector}</span>
									<span class="tabular-nums text-(--netz-muted)">
										{formatPercent(weight)}
									</span>
								</div>
							{/each}
						</div>
					{:else}
						<p class="text-sm text-(--netz-muted)">Style analysis not available yet.</p>
					{/if}
				</div>

				<!-- Fund info card -->
				<div class="border border-(--netz-border) rounded-lg p-4 bg-(--netz-surface)">
					<h3 class="text-sm font-medium text-(--netz-muted) mb-3">Fund Info</h3>
					<dl class="space-y-2 text-sm">
						{#if fund.inception_date}
							<div class="flex justify-between">
								<dt class="text-(--netz-muted)">Inception</dt>
								<dd class="text-(--netz-fg)">{fund.inception_date}</dd>
							</div>
						{/if}
						{#if fund.total_shareholder_accounts}
							<div class="flex justify-between">
								<dt class="text-(--netz-muted)">Shareholders</dt>
								<dd class="text-(--netz-fg) tabular-nums">
									{formatNumber(fund.total_shareholder_accounts)}
								</dd>
							</div>
						{/if}
						{#if fund.last_nport_date}
							<div class="flex justify-between">
								<dt class="text-(--netz-muted)">Last Filing</dt>
								<dd class="text-(--netz-fg)">{fund.last_nport_date}</dd>
							</div>
						{/if}
					</dl>
				</div>

				<!-- Adviser card -->
				<div class="border border-(--netz-border) rounded-lg p-4 bg-(--netz-surface)">
					<h3 class="text-sm font-medium text-(--netz-muted) mb-3">Adviser</h3>
					{#if fund.firm}
						<dl class="space-y-2 text-sm">
							<div class="flex justify-between">
								<dt class="text-(--netz-muted)">Firm</dt>
								<dd class="text-(--netz-fg) font-medium">{fund.firm.firm_name}</dd>
							</div>
							{#if fund.firm.aum_total}
								<div class="flex justify-between">
									<dt class="text-(--netz-muted)">Firm AUM</dt>
									<dd class="text-(--netz-fg) tabular-nums">{formatAUM(fund.firm.aum_total)}</dd>
								</div>
							{/if}
							{#if fund.firm.compliance_disclosures != null && fund.firm.compliance_disclosures > 0}
								<div class="flex justify-between">
									<dt class="text-(--netz-muted)">Disclosures</dt>
									<dd>
										<span class="inline-flex items-center rounded px-2 py-0.5 text-xs font-medium bg-red-100 text-red-800">
											{fund.firm.compliance_disclosures} disclosure{fund.firm.compliance_disclosures > 1 ? 's' : ''}
										</span>
									</dd>
								</div>
							{/if}
							{#if fund.firm.website}
								<div>
									<a
										href={fund.firm.website.startsWith("http") ? fund.firm.website : `https://${fund.firm.website}`}
										target="_blank"
										rel="noopener noreferrer"
										class="text-(--netz-accent) hover:underline text-sm"
									>
										{fund.firm.website} &nearr;
									</a>
								</div>
							{/if}
						</dl>
					{:else}
						<p class="text-sm text-(--netz-muted)">Adviser information not available.</p>
					{/if}
				</div>
			</div>

		<!-- Tab: Holdings -->
		{:else if activeTab === "holdings"}
			{#if !fund.data_availability.has_holdings}
				<EmptyState
					title="Holdings not available"
					message="Holdings are not publicly reported for this fund type."
				/>
			{:else if holdingsLoading}
				<div class="space-y-3">
					{#each Array(8) as _}
						<Skeleton class="h-10 w-full" />
					{/each}
				</div>
			{:else}
				<!-- Quarter selector -->
				{#if holdingsData.available_quarters.length > 0}
					<div class="flex items-center gap-3 mb-4">
						<label for="quarter-select" class="text-sm text-(--netz-muted)">Quarter:</label>
						<select
							id="quarter-select"
							class="rounded border border-(--netz-border) bg-(--netz-surface) px-3 py-1.5 text-sm text-(--netz-fg)"
							bind:value={selectedQuarter}
						>
							{#each holdingsData.available_quarters as q}
								<option value={q}>{q}</option>
							{/each}
						</select>
						<span class="text-sm text-(--netz-muted)">
							{formatNumber(holdingsData.total_count)} positions
							{#if holdingsData.total_value}
								&middot; {formatAUM(holdingsData.total_value)} total
							{/if}
						</span>
					</div>
				{/if}

				{#if holdingsData.holdings.length === 0}
					<EmptyState title="No holdings" message="No holdings data for this quarter." />
				{:else}
					<div class="overflow-x-auto">
						<table class="w-full text-sm">
							<thead>
								<tr class="border-b border-(--netz-border) text-left text-(--netz-muted)">
									<th class="pb-2 font-medium">Issuer</th>
									<th class="pb-2 font-medium">Asset Class</th>
									<th class="pb-2 font-medium">Sector</th>
									<th class="pb-2 font-medium text-right">Market Value</th>
									<th class="pb-2 font-medium text-right">% NAV</th>
									<th class="pb-2 font-medium">Fair Value</th>
								</tr>
							</thead>
							<tbody>
								{#each holdingsData.holdings as h, i (i)}
									<tr class="border-b border-(--netz-border)/50">
										<td class="py-2 font-medium text-(--netz-fg)">{h.issuer_name ?? "—"}</td>
										<td class="py-2 text-(--netz-muted)">{h.asset_class ?? "—"}</td>
										<td class="py-2 text-(--netz-muted)">{h.sector ?? "—"}</td>
										<td class="py-2 text-right tabular-nums">
											{h.market_value ? formatAUM(h.market_value) : "—"}
										</td>
										<td class="py-2 text-right tabular-nums">
											{h.pct_of_nav != null ? formatPercent(h.pct_of_nav) : "—"}
										</td>
										<td class="py-2 text-(--netz-muted)">{h.fair_value_level ?? "—"}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{/if}
			{/if}

		<!-- Tab: Style -->
		{:else if activeTab === "style"}
			{#if !fund.data_availability.has_style_analysis}
				<EmptyState
					title="Style analysis not available"
					message="Style analysis requires holdings data. Not available for this fund."
				/>
			{:else if styleHistory.snapshots.length === 0}
				<EmptyState title="No style data" message="No style classification history found." />
			{:else}
				<!-- Drift badge -->
				<div class="mb-4">
					{#if styleHistory.drift_detected}
						<span class="inline-flex items-center rounded px-3 py-1 text-sm font-medium bg-red-100 text-red-800">
							Style Changed
						</span>
					{:else}
						<span class="inline-flex items-center rounded px-3 py-1 text-sm font-medium bg-green-100 text-green-800">
							Consistent
						</span>
					{/if}
					<span class="ml-2 text-sm text-(--netz-muted)">
						{styleHistory.quarters_analyzed} quarters analyzed
					</span>
				</div>

				<!-- Style history table -->
				<div class="overflow-x-auto">
					<table class="w-full text-sm">
						<thead>
							<tr class="border-b border-(--netz-border) text-left text-(--netz-muted)">
								<th class="pb-2 font-medium">Date</th>
								<th class="pb-2 font-medium">Style</th>
								<th class="pb-2 font-medium">Growth Tilt</th>
								<th class="pb-2 font-medium text-right">Equity %</th>
								<th class="pb-2 font-medium text-right">Fixed Income %</th>
								<th class="pb-2 font-medium text-right">Confidence</th>
							</tr>
						</thead>
						<tbody>
							{#each styleHistory.snapshots as snap, i (snap.report_date)}
								<tr class="border-b border-(--netz-border)/50">
									<td class="py-2 text-(--netz-fg)">{snap.report_date}</td>
									<td class="py-2">
										<span class="inline-flex items-center rounded px-2 py-0.5 text-xs font-medium {STYLE_COLORS[snap.style_label] ?? STYLE_COLORS.unknown}">
											{styleLabel(snap.style_label)}
										</span>
									</td>
									<td class="py-2">
										<!-- Growth tilt bar -->
										<div class="flex items-center gap-2">
											<span class="text-xs text-(--netz-muted) w-10">Value</span>
											<div class="flex-1 h-2 bg-(--netz-border) rounded-full overflow-hidden">
												<div
													class="h-full bg-(--netz-accent) rounded-full transition-all"
													style="width: {snap.growth_tilt * 100}%"
												></div>
											</div>
											<span class="text-xs text-(--netz-muted) w-12">Growth</span>
										</div>
									</td>
									<td class="py-2 text-right tabular-nums">
										{snap.equity_pct != null ? formatPercent(snap.equity_pct) : "—"}
									</td>
									<td class="py-2 text-right tabular-nums">
										{snap.fixed_income_pct != null ? formatPercent(snap.fixed_income_pct) : "—"}
									</td>
									<td class="py-2 text-right tabular-nums">
										{formatPercent(snap.confidence)}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}

		<!-- Tab: Team -->
		{:else if activeTab === "team"}
			{#if !fund.data_availability.has_portfolio_manager}
				<EmptyState
					title="Team information not available"
					message="Portfolio manager data not found in regulatory filings."
				/>
			{:else if fund.team.length === 0}
				<EmptyState title="No team data" message="No portfolio managers found." />
			{:else}
				<div class="grid grid-cols-1 md:grid-cols-2 gap-4">
					{#each fund.team as member (member.person_name)}
						<div class="border border-(--netz-border) rounded-lg p-4 bg-(--netz-surface)">
							<h4 class="font-medium text-(--netz-fg)">{member.person_name}</h4>
							{#if member.title}
								<p class="text-sm text-(--netz-muted) mt-0.5">{member.title}</p>
							{/if}
							<div class="mt-2 flex flex-wrap gap-2">
								{#if member.role}
									<span class="inline-flex items-center rounded px-2 py-0.5 text-xs font-medium bg-(--netz-surface-raised) text-(--netz-muted)">
										{member.role}
									</span>
								{/if}
								{#if member.years_experience}
									<span class="inline-flex items-center rounded px-2 py-0.5 text-xs font-medium bg-(--netz-surface-raised) text-(--netz-muted)">
										{member.years_experience}y exp
									</span>
								{/if}
								{#each member.certifications as cert}
									<span class="inline-flex items-center rounded px-2 py-0.5 text-xs font-medium bg-blue-100 text-blue-800">
										{cert}
									</span>
								{/each}
							</div>
						</div>
					{/each}
				</div>
			{/if}
		{/if}
	{/if}
</div>
