<!--
  Manager detail — L1→L2: shows manager card + tabs for Mutual Funds & ETFs / Private Funds.
  Clicking a registered fund navigates to the fund fact sheet.
-->
<script lang="ts">
	import { goto } from "$app/navigation";
	import { StatusBadge, formatAUM, EmptyState } from "@netz/ui";
	import type { PageData } from "./$types";
	import type { RegisteredFundSummary, PrivateFundSummary } from "$lib/types/sec-funds";

	let { data }: { data: PageData } = $props();

	let manager = $derived(data.manager);
	let registeredFunds = $derived(data.registeredFunds?.funds ?? []);
	let privateFunds = $derived(data.privateFunds?.funds ?? []);

	let activeTab = $state<"registered" | "private">("registered");

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

	const FUND_TYPE_LABELS: Record<string, string> = {
		mutual_fund: "Mutual Fund",
		etf: "ETF",
		closed_end: "Closed-End",
		interval_fund: "Interval",
		"Hedge Fund": "Hedge Fund",
		"Private Equity": "PE",
		"Venture Capital": "VC",
		"Real Estate": "Real Estate",
		"Securitized Asset": "Securitized",
		Liquidity: "Liquidity",
		Other: "Other",
	};

	function styleLabel(label: string): string {
		return label.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
	}
</script>

<div class="space-y-6">
	<!-- Back link -->
	<button
		class="text-sm text-(--netz-muted) hover:text-(--netz-fg) transition-colors"
		onclick={() => goto("/us-fund-analysis")}
	>
		&larr; Back to Manager Search
	</button>

	{#if !manager}
		<EmptyState title="Manager not found" message="No data available for this CRD number." />
	{:else}
		<!-- Manager card -->
		<div class="border border-(--netz-border) rounded-lg p-6 bg-(--netz-surface)">
			<div class="flex items-start justify-between gap-4">
				<div>
					<h1 class="text-xl font-semibold text-(--netz-fg)">{manager.firm_name}</h1>
					<div class="mt-1 flex flex-wrap gap-3 text-sm text-(--netz-muted)">
						{#if manager.state}
							<span>{manager.state}</span>
						{/if}
						{#if manager.aum_total}
							<span>AUM {formatAUM(manager.aum_total)}</span>
						{/if}
						{#if manager.registration_status}
							<StatusBadge status={manager.registration_status} />
						{/if}
					</div>
				</div>
				<div class="text-right text-sm text-(--netz-muted)">
					<div>CRD: {data.crd}</div>
					{#if manager.cik}
						<div>CIK: {manager.cik}</div>
					{/if}
					{#if manager.website}
						<a
							href={manager.website.startsWith("http") ? manager.website : `https://${manager.website}`}
							target="_blank"
							rel="noopener noreferrer"
							class="text-(--netz-accent) hover:underline"
						>
							Website &nearr;
						</a>
					{/if}
				</div>
			</div>
		</div>

		<!-- Tabs -->
		<div class="border-b border-(--netz-border)">
			<nav class="flex gap-6">
				<button
					class="pb-2 text-sm font-medium transition-colors {activeTab === 'registered'
						? 'border-b-2 border-(--netz-accent) text-(--netz-fg)'
						: 'text-(--netz-muted) hover:text-(--netz-fg)'}"
					onclick={() => (activeTab = "registered")}
				>
					Mutual Funds & ETFs
					{#if registeredFunds.length > 0}
						<span class="ml-1 text-xs text-(--netz-muted)">({registeredFunds.length})</span>
					{/if}
				</button>
				<button
					class="pb-2 text-sm font-medium transition-colors {activeTab === 'private'
						? 'border-b-2 border-(--netz-accent) text-(--netz-fg)'
						: 'text-(--netz-muted) hover:text-(--netz-fg)'}"
					onclick={() => (activeTab = "private")}
				>
					Private Funds
					{#if privateFunds.length > 0}
						<span class="ml-1 text-xs text-(--netz-muted)">({privateFunds.length})</span>
					{/if}
				</button>
			</nav>
		</div>

		<!-- Tab content -->
		{#if activeTab === "registered"}
			{#if registeredFunds.length === 0}
				<EmptyState
					title="No registered funds"
					message="No registered funds with AUM ≥ $50M found for this adviser."
				/>
			{:else}
				<div class="overflow-x-auto">
					<table class="w-full text-sm">
						<thead>
							<tr class="border-b border-(--netz-border) text-left text-(--netz-muted)">
								<th class="pb-2 font-medium">Fund Name</th>
								<th class="pb-2 font-medium">Type</th>
								<th class="pb-2 font-medium text-right">AUM</th>
								<th class="pb-2 font-medium">Style</th>
								<th class="pb-2 font-medium">Ticker</th>
								<th class="pb-2 font-medium">Last Filing</th>
								<th class="pb-2 font-medium w-8"></th>
							</tr>
						</thead>
						<tbody>
							{#each registeredFunds as fund (fund.cik)}
								<tr
									class="border-b border-(--netz-border)/50 hover:bg-(--netz-hover) cursor-pointer transition-colors"
									onclick={() => goto(`/us-fund-analysis/${data.crd}/${fund.cik}`)}
								>
									<td class="py-3 font-medium text-(--netz-fg)">{fund.fund_name}</td>
									<td class="py-3">
										<span class="inline-flex items-center rounded px-2 py-0.5 text-xs font-medium bg-(--netz-surface-raised) text-(--netz-muted)">
											{FUND_TYPE_LABELS[fund.fund_type] ?? fund.fund_type}
										</span>
									</td>
									<td class="py-3 text-right tabular-nums">
										{fund.total_assets ? formatAUM(fund.total_assets) : "—"}
									</td>
									<td class="py-3">
										{#if fund.style_label}
											<span class="inline-flex items-center rounded px-2 py-0.5 text-xs font-medium {STYLE_COLORS[fund.style_label] ?? STYLE_COLORS.unknown}">
												{styleLabel(fund.style_label)}
											</span>
										{:else}
											<span class="text-(--netz-muted)">—</span>
										{/if}
									</td>
									<td class="py-3 tabular-nums text-(--netz-muted)">
										{fund.ticker ?? "—"}
									</td>
									<td class="py-3 text-(--netz-muted)">
										{fund.last_nport_date ?? "—"}
									</td>
									<td class="py-3 text-(--netz-muted)">&rarr;</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		{:else}
			{#if privateFunds.length === 0}
				<EmptyState
					title="No private funds"
					message="No Schedule D private fund data available for this adviser."
				/>
			{:else}
				<div class="overflow-x-auto">
					<table class="w-full text-sm">
						<thead>
							<tr class="border-b border-(--netz-border) text-left text-(--netz-muted)">
								<th class="pb-2 font-medium">Fund Name</th>
								<th class="pb-2 font-medium">Type</th>
								<th class="pb-2 font-medium text-right">GAV</th>
								<th class="pb-2 font-medium text-right">Investors</th>
								<th class="pb-2 font-medium">Fund of Funds</th>
							</tr>
						</thead>
						<tbody>
							{#each privateFunds as fund, i (i)}
								<tr class="border-b border-(--netz-border)/50">
									<td class="py-3 font-medium text-(--netz-fg)">{fund.fund_name}</td>
									<td class="py-3">
										{#if fund.fund_type}
											<span class="inline-flex items-center rounded px-2 py-0.5 text-xs font-medium bg-(--netz-surface-raised) text-(--netz-muted)">
												{FUND_TYPE_LABELS[fund.fund_type] ?? fund.fund_type}
											</span>
										{:else}
											<span class="text-(--netz-muted)">—</span>
										{/if}
									</td>
									<td class="py-3 text-right tabular-nums">
										{fund.gross_asset_value ? formatAUM(fund.gross_asset_value) : "—"}
									</td>
									<td class="py-3 text-right tabular-nums">
										{fund.investor_count ?? "—"}
									</td>
									<td class="py-3">
										{fund.is_fund_of_funds ? "Yes" : fund.is_fund_of_funds === false ? "No" : "—"}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		{/if}
	{/if}
</div>
