<!--
  Individual Fund Fact Sheet Page.
  Consolidated view of team, returns, holdings, and NAV history.
  Designed for fund-centric deep dives and print-ready reports.
-->
<script lang="ts">
	import { formatCompact, formatPercent, formatDate, ContextPanel } from "@investintell/ui";
	import NavPerformanceChart from "$lib/components/charts/NavPerformanceChart.svelte";
	import SectorAllocationChart from "$lib/components/charts/SectorAllocationChart.svelte";
	import SectorAllocationTreemap from "$lib/components/charts/SectorAllocationTreemap.svelte";
	import FundScoringRadar from "$lib/components/charts/FundScoringRadar.svelte";
	import DecileBoxplot from "$lib/components/charts/DecileBoxplot.svelte";
	import ReverseLookupPanel from "$lib/components/holdings/ReverseLookupPanel.svelte";
	import "./factsheet.css";

	let { data } = $props();
	const { factSheet } = data;
	const { 
		fund, team, top_holdings, annual_returns, 
		nav_history, sector_history, prospectus_stats, 
		share_classes, scoring_metrics 
	} = factSheet;

	// ── Reverse Lookup State ──
	let rlOpen = $state(false);
	let rlTarget = $state<{ cusip?: string | null, isin?: string | null, name: string } | null>(null);

	function openReverseLookup(holding: any) {
		rlTarget = { cusip: holding.cusip, isin: holding.isin, name: holding.name };
		rlOpen = true;
	}

	function formatAum(val: number | null | undefined) {
		if (val == null) return "\u2014";
		return formatCompact(val);
	}
</script>

<svelte:head>
	<title>{fund.name} | Fact Sheet</title>
</svelte:head>

<div class="fs-container">
	<!-- ── Header ── -->
	<header class="fs-header">
		<div class="fs-header-top">
			<div class="fs-brand">
				<span class="fs-universe-badge">{fund.universe.replace("_", " ").toUpperCase()}</span>
				<h1 class="fs-fund-name">{fund.name}</h1>
				{#if fund.ticker}
					<span class="fs-ticker">{fund.ticker}</span>
				{/if}
			</div>
			<div class="fs-manager-box">
				<span class="fs-mgr-label">Investment Manager</span>
				<div class="fs-mgr-name">{fund.manager_name || "Standalone"}</div>
				{#if fund.manager_id}
					<span class="fs-mgr-id">ID: {fund.manager_id}</span>
				{/if}
			</div>
		</div>

		<div class="fs-quick-stats">
			<div class="fs-stat">
				<span class="fs-stat-label">AUM</span>
				<span class="fs-stat-val">{formatAum(fund.aum)}</span>
			</div>
			<div class="fs-stat">
				<span class="fs-stat-label">Inception</span>
				<span class="fs-stat-val">{fund.inception_date ? formatDate(fund.inception_date) : "\u2014"}</span>
			</div>
			<div class="fs-stat">
				<span class="fs-stat-label">Strategy</span>
				<span class="fs-stat-val">{fund.strategy_label || fund.fund_type}</span>
			</div>
			<div class="fs-stat">
				<span class="fs-stat-label">Geography</span>
				<span class="fs-stat-val">{fund.investment_geography || "\u2014"}</span>
			</div>
			<div class="fs-stat">
				<span class="fs-stat-label">Exp. Ratio</span>
				<span class="fs-stat-val">{fund.expense_ratio_pct != null ? formatPercent(fund.expense_ratio_pct / 100) : "\u2014"}</span>
			</div>
		</div>
	</header>

	<div class="fs-grid">
		<!-- ── Left Column: Analysis ── -->
		<div class="fs-col-left">
			<!-- Scoring Radar -->
			<section class="fs-section">
				<h3 class="fs-section-title">Fund Analysis Score</h3>
				<div class="fs-chart-wrap">
					{#if scoring_metrics}
						<FundScoringRadar scoringMetrics={scoring_metrics} height={350} />
					{:else}
						<div class="fs-no-data">Scoring data not available for this instrument.</div>
					{/if}
				</div>
			</section>

			<!-- Peer Ranking -->
			<section class="fs-section">
				<h3 class="fs-section-title">Peer Group Ranking</h3>
				<div class="fs-chart-wrap">
					{#if scoring_metrics?.peer_percentiles}
						<DecileBoxplot 
							percentiles={scoring_metrics.peer_percentiles} 
							strategy={scoring_metrics.peer_strategy || fund.strategy_label || "Category"}
							height={300} 
						/>
					{:else}
						<div class="fs-no-data">Peer ranking not available.</div>
					{/if}
				</div>
			</section>

			<!-- NAV Chart -->
			<section class="fs-section">
				<h3 class="fs-section-title">Historical Performance (Growth)</h3>
				<div class="fs-chart-wrap">
					{#if nav_history && nav_history.length > 0}
						<NavPerformanceChart navData={nav_history} height={300} />
					{:else}
						<div class="fs-no-data">Historical NAV data not available for this instrument.</div>
					{/if}
				</div>
			</section>

			<!-- Sector Evolution Chart -->
			<section class="fs-section">
				<h3 class="fs-section-title">Sector Allocation Evolution</h3>
				<div class="fs-chart-wrap">
					{#if sector_history && sector_history.length > 0}
						<SectorAllocationChart history={sector_history} height={350} />
					{:else}
						<div class="fs-no-data">Historical sector allocation not available.</div>
					{/if}
				</div>
			</section>

			<!-- Annual Returns -->
			<section class="fs-section">
				<h3 class="fs-section-title">Annual Performance</h3>
				{#if annual_returns.length > 0}
					<div class="fs-returns-grid">
						{#each annual_returns as r}
							<div class="fs-ret-card">
								<span class="fs-ret-year">{r.year}</span>
								<span class="fs-ret-val" class:neg={r.annual_return_pct < 0}>
									{formatPercent(r.annual_return_pct / 100)}
								</span>
							</div>
						{/each}
					</div>
				{:else}
					<div class="fs-no-data">Annual return history not available.</div>
				{/if}
			</section>

			<!-- Share Classes -->
			<section class="fs-section">
				<h3 class="fs-section-title">Available Share Classes</h3>
				<table class="fs-table">
					<thead>
						<tr>
							<th>Class</th>
							<th>Ticker</th>
							<th class="r">ER%</th>
							<th class="r">1Y Ret</th>
							<th class="r">Net Assets</th>
						</tr>
					</thead>
					<tbody>
						{#each share_classes as sc}
							<tr>
								<td>{sc.class_id || "Primary"}</td>
								<td><code class="fs-mini-ticker">{sc.ticker || "\u2014"}</code></td>
								<td class="r">{sc.expense_ratio_pct != null ? formatPercent(sc.expense_ratio_pct / 100) : "\u2014"}</td>
								<td class="r">{sc.avg_annual_return_pct != null ? formatPercent(sc.avg_annual_return_pct / 100) : "\u2014"}</td>
								<td class="r">{formatAum(sc.net_assets)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</section>
		</div>

		<!-- ── Right Column: Components ── -->
		<div class="fs-col-right">
			<!-- Management Team -->
			<section class="fs-section">
				<h3 class="fs-section-title">Management Team</h3>
				<div class="fs-team-list">
					{#each team as member}
						<div class="fs-team-card">
							<div class="fs-team-name">{member.person_name}</div>
							<div class="fs-team-role">{member.title || member.role || "Portfolio Manager"}</div>
							{#if member.bio_summary}
								<p class="fs-team-bio">{member.bio_summary}</p>
							{/if}
							{#if member.education || (member.certifications && member.certifications.length > 0)}
								<div class="fs-team-meta">
									{member.education || ""} 
									{member.certifications?.join(", ") || ""}
								</div>
							{/if}
						</div>
					{/each}
					{#if team.length === 0}
						<div class="fs-no-data">Team background not disclosed in current filings.</div>
					{/if}
				</div>
			</section>

			<!-- Current Allocation Treemap -->
			<section class="fs-section">
				<h3 class="fs-section-title">Current Sector Allocation</h3>
				<div class="fs-chart-wrap">
					{#if sector_history && sector_history.length > 0}
						<SectorAllocationTreemap 
							sectorWeights={sector_history[sector_history.length - 1].sector_weights} 
							height={350} 
						/>
					{:else}
						<div class="fs-no-data">Current allocation data not available.</div>
					{/if}
				</div>
			</section>

			<!-- Top Holdings -->
			<section class="fs-section">
				<h3 class="fs-section-title">Top Portfolio Holdings</h3>
				<table class="fs-table fs-table--compact">
					<thead>
						<tr>
							<th>Holding</th>
							<th class="r">Weight</th>
						</tr>
					</thead>
					<tbody>
						{#each top_holdings as h, i}
							<tr class={i >= 10 ? "fs-print-hide" : ""}>
								<td>
									<button 
										class="fs-holding-btn" 
										onclick={() => openReverseLookup(h)}
										title="Reverse Lookup: find other holders"
									>
										<div class="fs-holding-name">{h.name}</div>
									</button>
									<div class="fs-holding-meta">{h.sector || "Other"}</div>
								</td>
								<td class="r fs-holding-weight">{formatPercent(h.pct_of_nav / 100)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
				{#if top_holdings.length === 0}
					<div class="fs-no-data">Recent holdings (N-PORT) not available for this fund.</div>
				{/if}
			</section>
		</div>
	</div>
</div>

<!-- Reverse Lookup Sidebar (Non-printable) -->
<ContextPanel 
	open={rlOpen} 
	onClose={() => { rlOpen = false; rlTarget = null; }} 
	title="Reverse Lookup"
>
	{#if rlTarget}
		<div class="rl-container">
			<ReverseLookupPanel 
				cusip={rlTarget.cusip} 
				isin={rlTarget.isin} 
				assetName={rlTarget.name} 
			/>
		</div>
	{/if}
</ContextPanel>

<style>
	.rl-container {
		padding: 20px;
	}
</style>
