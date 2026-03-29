<!--
  Fund Detail Page — 4-tab view with Overview, Portfolio Holdings,
  Peer Analysis, and Institutional Holders.
-->
<script lang="ts">
	import { PageHeader, formatAUM, formatPercent, formatNumber, formatCurrency, ChartContainer } from "@investintell/ui";
	import { Button } from "@investintell/ui/components/ui/button";

	let { data }: { data: Record<string, any> } = $props();

	type DetailTab = "overview" | "holdings" | "peers" | "holders";
	let activeTab = $state<DetailTab>("overview");

	const detail = $derived(data.detail as Record<string, any> | null);
	const prospectus = $derived(data.prospectus as Record<string, any> | null);
	const peers = $derived(data.peers as Record<string, any> | null);
	const reverseHoldings = $derived(data.reverseHoldings as Record<string, any> | null);
	const holdingsHistory = $derived(data.holdingsHistory as Record<string, any> | null);
	const holdings = $derived(data.holdings as Record<string, any> | null);

	const fundName = $derived(detail?.fund_name ?? `Fund ${data.cik}`);

	// ── Stacked Area Chart — Sector Weights over Time ──
	let sectorChartOption = $derived.by(() => {
		if (!holdingsHistory?.quarters?.length) return null;
		const quarters: string[] = holdingsHistory.quarters;
		const series: Record<string, (number | null)[]> = holdingsHistory.sector_series;
		return {
			tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
			legend: { type: "scroll", bottom: 0 },
			grid: { left: 60, right: 20, top: 20, bottom: 60 },
			xAxis: { type: "category", data: quarters.map((q: string) => q.slice(0, 7)) },
			yAxis: { type: "value", axisLabel: { formatter: "{value}%" } },
			series: Object.entries(series)
				.filter(([, vals]) => vals.some((v) => v !== null && v > 0.01))
				.map(([sector, values]) => ({
					name: sector,
					type: "line",
					stack: "total",
					areaStyle: {},
					emphasis: { focus: "series" },
					data: (values as (number | null)[]).map((v) => (v !== null ? +(v * 100).toFixed(1) : null)),
				})),
		};
	});

	// ── Scatter Plot — Peer ER vs 1Y Return ──
	let peerScatterOption = $derived.by(() => {
		if (!peers?.peers?.length) return null;
		const peerData = peers.peers
			.filter((p: any) => p.expense_ratio_pct != null && p.avg_annual_return_1y != null)
			.map((p: any) => [p.expense_ratio_pct, p.avg_annual_return_1y]);
		const targetPoint =
			peers.target.expense_ratio_pct != null && peers.target.avg_annual_return_1y != null
				? [[peers.target.expense_ratio_pct, peers.target.avg_annual_return_1y]]
				: [];
		return {
			tooltip: {
				trigger: "item",
				formatter: (p: any) => `ER: ${p.value[0]}% | 1Y: ${p.value[1]}%`,
			},
			grid: { left: 60, right: 20, top: 20, bottom: 40 },
			xAxis: { name: "Expense Ratio (%)", type: "value", nameLocation: "middle", nameGap: 28 },
			yAxis: { name: "1Y Return (%)", type: "value", nameLocation: "middle", nameGap: 40 },
			series: [
				{
					type: "scatter",
					data: peerData,
					symbolSize: 6,
					itemStyle: { color: "#94A3B8" },
					name: "Peers",
				},
				...(targetPoint.length
					? [
							{
								type: "scatter",
								data: targetPoint,
								symbolSize: 14,
								itemStyle: { color: "#155dfc" },
								label: { show: true, formatter: "This Fund", position: "right", fontSize: 11 },
								name: "This Fund",
							},
						]
					: []),
			],
		};
	});

	const tabs: { key: DetailTab; label: string }[] = [
		{ key: "overview", label: "Overview" },
		{ key: "holdings", label: "Portfolio Holdings" },
		{ key: "peers", label: "Peer Analysis" },
		{ key: "holders", label: "Institutional Holders" },
	];

	// Holdings quarter selector
	let selectedQuarter = $state<string | null>(null);
	let holdingsForQuarter = $derived.by(() => {
		if (!holdings?.holdings) return [];
		return holdings.holdings;
	});
	let availableQuarters = $derived(holdings?.available_quarters ?? []);

	function fmtPct(v: number | null | undefined): string {
		if (v == null) return "—";
		return formatPercent(v / 100);
	}

	function fmtVal(v: number | null | undefined): string {
		if (v == null) return "—";
		return formatCurrency(v, "USD");
	}

	function percentileColor(pct: number | null | undefined): string {
		if (pct == null) return "#90a1b9";
		if (pct >= 75) return "#059669";
		if (pct >= 50) return "#d97706";
		return "#dc2626";
	}
</script>

<PageHeader title={fundName}>
	{#snippet actions()}
		<Button variant="outline" size="sm" onclick={() => history.back()}>Back to Screener</Button>
	{/snippet}
</PageHeader>

<!-- Tab bar -->
<div class="fd-tabs">
	{#each tabs as tab (tab.key)}
		<button
			class="fd-tab"
			class:fd-tab--active={activeTab === tab.key}
			onclick={() => (activeTab = tab.key)}
		>
			{tab.label}
		</button>
	{/each}
</div>

<div class="fd-content">
	<!-- ════════════════ OVERVIEW TAB ════════════════ -->
	{#if activeTab === "overview"}
		<div class="fd-grid">
			<!-- Fund Header -->
			<div class="fd-card fd-card--full">
				<h3 class="fd-card-title">Fund Information</h3>
				<div class="fd-meta-grid">
					{#if detail?.ticker}<div class="fd-kv"><span class="fd-k">Ticker</span><span class="fd-v">{detail.ticker}</span></div>{/if}
					{#if detail?.fund_type}<div class="fd-kv"><span class="fd-k">Type</span><span class="fd-v">{detail.fund_type.replace(/_/g, " ")}</span></div>{/if}
					{#if detail?.total_assets != null}<div class="fd-kv"><span class="fd-k">AUM</span><span class="fd-v">{formatAUM(detail.total_assets)}</span></div>{/if}
					{#if detail?.inception_date}<div class="fd-kv"><span class="fd-k">Inception</span><span class="fd-v">{detail.inception_date}</span></div>{/if}
					{#if detail?.domicile}<div class="fd-kv"><span class="fd-k">Domicile</span><span class="fd-v">{detail.domicile}</span></div>{/if}
					{#if detail?.currency}<div class="fd-kv"><span class="fd-k">Currency</span><span class="fd-v">{detail.currency}</span></div>{/if}
					{#if detail?.isin}<div class="fd-kv"><span class="fd-k">ISIN</span><span class="fd-v">{detail.isin}</span></div>{/if}
					{#if detail?.firm?.firm_name}<div class="fd-kv"><span class="fd-k">Manager</span><span class="fd-v">{detail.firm.firm_name}</span></div>{/if}
					{#if detail?.latest_style?.style_label}<div class="fd-kv"><span class="fd-k">Style</span><span class="fd-v">{detail.latest_style.style_label}</span></div>{/if}
				</div>
			</div>

			<!-- Prospectus Fee Table -->
			{#if prospectus}
				<div class="fd-card">
					<h3 class="fd-card-title">Fee Table (Prospectus)</h3>
					<div class="fd-fee-grid">
						<div class="fd-kv"><span class="fd-k">Expense Ratio</span><span class="fd-v">{fmtPct(prospectus.fees?.expense_ratio_pct)}</span></div>
						<div class="fd-kv"><span class="fd-k">Net Expense Ratio</span><span class="fd-v">{fmtPct(prospectus.fees?.net_expense_ratio_pct)}</span></div>
						<div class="fd-kv"><span class="fd-k">Management Fee</span><span class="fd-v">{fmtPct(prospectus.fees?.management_fee_pct)}</span></div>
						<div class="fd-kv"><span class="fd-k">12b-1 Fee</span><span class="fd-v">{fmtPct(prospectus.fees?.distribution_12b1_pct)}</span></div>
						<div class="fd-kv"><span class="fd-k">Turnover</span><span class="fd-v">{fmtPct(prospectus.fees?.portfolio_turnover_pct)}</span></div>
						{#if prospectus.fees?.fee_waiver_pct != null}
							<div class="fd-kv"><span class="fd-k">Fee Waiver</span><span class="fd-v">{fmtPct(prospectus.fees.fee_waiver_pct)}</span></div>
						{/if}
					</div>
					{#if prospectus.fees?.expense_examples}
						<div class="fd-expense-ex">
							<span class="fd-k">Cost of $10,000 investment:</span>
							<span>1Y: ${prospectus.fees.expense_examples["1y"] ?? "—"}</span>
							<span>3Y: ${prospectus.fees.expense_examples["3y"] ?? "—"}</span>
							<span>5Y: ${prospectus.fees.expense_examples["5y"] ?? "—"}</span>
							<span>10Y: ${prospectus.fees.expense_examples["10y"] ?? "—"}</span>
						</div>
					{/if}
				</div>

				<!-- Average Annual Returns -->
				<div class="fd-card">
					<h3 class="fd-card-title">Average Annual Returns</h3>
					<div class="fd-return-cards">
						<div class="fd-return-card">
							<span class="fd-return-label">1 Year</span>
							<span class="fd-return-value">{fmtPct(prospectus.avg_annual_returns?.["1y"])}</span>
						</div>
						<div class="fd-return-card">
							<span class="fd-return-label">5 Year</span>
							<span class="fd-return-value">{fmtPct(prospectus.avg_annual_returns?.["5y"])}</span>
						</div>
						<div class="fd-return-card">
							<span class="fd-return-label">10 Year</span>
							<span class="fd-return-value">{fmtPct(prospectus.avg_annual_returns?.["10y"])}</span>
						</div>
					</div>

					{#if prospectus.annual_returns?.length}
						<h4 class="fd-subtitle">Annual Returns History</h4>
						<div class="fd-returns-table">
							<table>
								<thead><tr><th>Year</th><th>Return</th></tr></thead>
								<tbody>
									{#each prospectus.annual_returns as r (r.year)}
										<tr>
											<td>{r.year}</td>
											<td class:fd-positive={r.annual_return_pct > 0} class:fd-negative={r.annual_return_pct < 0}>
												{fmtPct(r.annual_return_pct)}
											</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					{/if}
				</div>
			{:else}
				<div class="fd-card">
					<h3 class="fd-card-title">Prospectus Data</h3>
					<p class="fd-empty">Prospectus data not available for this fund.</p>
				</div>
			{/if}
		</div>

	<!-- ════════════════ HOLDINGS TAB ════════════════ -->
	{:else if activeTab === "holdings"}
		<div class="fd-grid">
			<!-- Sector Evolution Chart -->
			{#if sectorChartOption}
				<div class="fd-card fd-card--full">
					<h3 class="fd-card-title">Sector Weight Evolution ({holdingsHistory?.quarters_available ?? 0} quarters)</h3>
					<ChartContainer option={sectorChartOption} height={400} ariaLabel="Sector weights over time" />
				</div>
			{/if}

			<!-- Holdings Table -->
			<div class="fd-card fd-card--full">
				<div class="fd-card-header-row">
					<h3 class="fd-card-title">Holdings</h3>
					{#if availableQuarters.length > 1}
						<select class="fd-select" bind:value={selectedQuarter}>
							{#each availableQuarters as q (q)}
								<option value={q}>{q}</option>
							{/each}
						</select>
					{/if}
				</div>
				{#if holdingsForQuarter.length}
					<div class="fd-table-wrap">
						<table class="fd-table">
							<thead>
								<tr>
									<th>Issuer</th>
									<th>Sector</th>
									<th class="fd-num">% of NAV</th>
									<th class="fd-num">Market Value</th>
								</tr>
							</thead>
							<tbody>
								{#each holdingsForQuarter as h (h.cusip ?? h.issuer_name)}
									<tr>
										<td>{h.issuer_name ?? "—"}</td>
										<td>{h.sector ?? "—"}</td>
										<td class="fd-num">{h.pct_of_nav != null ? formatPercent(h.pct_of_nav) : "—"}</td>
										<td class="fd-num">{h.market_value != null ? formatCurrency(h.market_value, "USD") : "—"}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{:else}
					<p class="fd-empty">No holdings data available.</p>
				{/if}
			</div>

			<!-- Top Holdings Latest -->
			{#if holdingsHistory?.top_holdings_latest?.length}
				<div class="fd-card fd-card--full">
					<h3 class="fd-card-title">Top 20 Holdings (Latest Quarter)</h3>
					<div class="fd-table-wrap">
						<table class="fd-table">
							<thead>
								<tr>
									<th>#</th>
									<th>Issuer</th>
									<th>Sector</th>
									<th class="fd-num">% of NAV</th>
									<th class="fd-num">Market Value</th>
								</tr>
							</thead>
							<tbody>
								{#each holdingsHistory.top_holdings_latest as h, i (h.cusip ?? i)}
									<tr>
										<td class="fd-rank">{i + 1}</td>
										<td>{h.issuer_name ?? "—"}</td>
										<td>{h.sector ?? "—"}</td>
										<td class="fd-num">{h.pct_of_nav != null ? formatPercent(h.pct_of_nav) : "—"}</td>
										<td class="fd-num">{h.market_value != null ? formatCurrency(h.market_value, "USD") : "—"}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				</div>
			{/if}
		</div>

	<!-- ════════════════ PEER ANALYSIS TAB ════════════════ -->
	{:else if activeTab === "peers"}
		{#if peers}
			<div class="fd-grid">
				<!-- Percentile Cards -->
				<div class="fd-card fd-card--full">
					<h3 class="fd-card-title">Peer Group: {peers.peer_group ?? "—"} ({peers.peer_count} peers)</h3>
					<div class="fd-pctile-grid">
						<div class="fd-pctile-card">
							<span class="fd-pctile-label">Expense Ratio</span>
							<span class="fd-pctile-value" style:color={percentileColor(peers.percentiles?.expense_ratio_pct)}>
								{peers.percentiles?.expense_ratio_pct != null ? `P${peers.percentiles.expense_ratio_pct}` : "—"}
							</span>
							<span class="fd-pctile-note">lower ER = higher percentile</span>
						</div>
						<div class="fd-pctile-card">
							<span class="fd-pctile-label">1Y Return</span>
							<span class="fd-pctile-value" style:color={percentileColor(peers.percentiles?.avg_annual_return_1y)}>
								{peers.percentiles?.avg_annual_return_1y != null ? `P${peers.percentiles.avg_annual_return_1y}` : "—"}
							</span>
						</div>
						<div class="fd-pctile-card">
							<span class="fd-pctile-label">5Y Return</span>
							<span class="fd-pctile-value" style:color={percentileColor(peers.percentiles?.avg_annual_return_5y)}>
								{peers.percentiles?.avg_annual_return_5y != null ? `P${peers.percentiles.avg_annual_return_5y}` : "—"}
							</span>
						</div>
						<div class="fd-pctile-card">
							<span class="fd-pctile-label">10Y Return</span>
							<span class="fd-pctile-value" style:color={percentileColor(peers.percentiles?.avg_annual_return_10y)}>
								{peers.percentiles?.avg_annual_return_10y != null ? `P${peers.percentiles.avg_annual_return_10y}` : "—"}
							</span>
						</div>
					</div>
				</div>

				<!-- Scatter Plot -->
				{#if peerScatterOption}
					<div class="fd-card fd-card--full">
						<h3 class="fd-card-title">Expense Ratio vs 1Y Return</h3>
						<ChartContainer option={peerScatterOption} height={360} ariaLabel="Peer comparison scatter plot" />
					</div>
				{/if}

				<!-- Peer Table -->
				<div class="fd-card fd-card--full">
					<h3 class="fd-card-title">Top Peers</h3>
					<div class="fd-table-wrap">
						<table class="fd-table">
							<thead>
								<tr>
									<th>Fund</th>
									<th>Ticker</th>
									<th class="fd-num">ER %</th>
									<th class="fd-num">1Y %</th>
									<th class="fd-num">5Y %</th>
									<th class="fd-num">10Y %</th>
								</tr>
							</thead>
							<tbody>
								{#each peers.peers.slice(0, 20) as p (p.cik)}
									<tr>
										<td class="fd-fund-name">{p.fund_name ?? "—"}</td>
										<td>{p.ticker ?? "—"}</td>
										<td class="fd-num">{p.expense_ratio_pct != null ? formatNumber(p.expense_ratio_pct, 2) : "—"}</td>
										<td class="fd-num">{p.avg_annual_return_1y != null ? formatNumber(p.avg_annual_return_1y, 1) : "—"}</td>
										<td class="fd-num">{p.avg_annual_return_5y != null ? formatNumber(p.avg_annual_return_5y, 1) : "—"}</td>
										<td class="fd-num">{p.avg_annual_return_10y != null ? formatNumber(p.avg_annual_return_10y, 1) : "—"}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				</div>
			</div>
		{:else}
			<div class="fd-empty-section">
				<p class="fd-empty">Peer analysis not available for this fund. Requires style classification and prospectus data.</p>
			</div>
		{/if}

	<!-- ════════════════ INSTITUTIONAL HOLDERS TAB ════════════════ -->
	{:else if activeTab === "holders"}
		{#if reverseHoldings && reverseHoldings.holders?.length}
			<div class="fd-grid">
				<div class="fd-card fd-card--full">
					<h3 class="fd-card-title">
						Institutional Holders
						{#if reverseHoldings.fund_ticker}
							— {reverseHoldings.fund_ticker}
						{/if}
					</h3>
					<div class="fd-holder-summary">
						<div class="fd-holder-stat">
							<span class="fd-holder-val">{formatNumber(reverseHoldings.total_holders, 0)}</span>
							<span class="fd-holder-lbl">Total Holders</span>
						</div>
						<div class="fd-holder-stat">
							<span class="fd-holder-val">{formatCurrency(reverseHoldings.total_market_value, "USD")}</span>
							<span class="fd-holder-lbl">Total Market Value</span>
						</div>
					</div>
					<div class="fd-table-wrap">
						<table class="fd-table">
							<thead>
								<tr>
									<th>Institution</th>
									<th>Type</th>
									<th class="fd-num">Market Value</th>
									<th class="fd-num">Shares</th>
									<th>Date</th>
								</tr>
							</thead>
							<tbody>
								{#each reverseHoldings.holders as h (h.filer_cik)}
									<tr>
										<td class="fd-fund-name">{h.filer_name ?? h.filer_cik}</td>
										<td>{h.filer_type ?? "—"}</td>
										<td class="fd-num">{h.market_value != null ? formatCurrency(h.market_value, "USD") : "—"}</td>
										<td class="fd-num">{h.shares != null ? formatNumber(h.shares, 0) : "—"}</td>
										<td>{h.report_date ?? "—"}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				</div>
			</div>
		{:else}
			<div class="fd-empty-section">
				<p class="fd-empty">
					{reverseHoldings?.note ?? "No institutional holders data available. CUSIP resolution required for 13F reverse lookup."}
				</p>
			</div>
		{/if}
	{/if}
</div>

<style>
	.fd-tabs {
		display: flex;
		gap: 0;
		border-bottom: 1px solid #e2e8f0;
		margin-bottom: 24px;
	}

	.fd-tab {
		padding: 12px 24px;
		border: none;
		border-bottom: 2px solid transparent;
		background: none;
		font-size: 14px;
		font-weight: 600;
		color: #62748e;
		cursor: pointer;
		font-family: var(--ii-font-sans);
		transition: color 120ms, border-color 120ms;
		white-space: nowrap;
	}

	.fd-tab:hover { color: #1d293d; }

	.fd-tab--active {
		color: #1447e6;
		border-bottom-color: #155dfc;
	}

	.fd-content {
		padding-bottom: 48px;
	}

	.fd-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 20px;
	}

	.fd-card {
		background: white;
		border: 1px solid #e2e8f0;
		border-radius: 16px;
		padding: 24px;
		box-shadow: 0 1px 3px rgba(0,0,0,0.1), 0 1px 2px -1px rgba(0,0,0,0.1);
	}

	.fd-card--full {
		grid-column: 1 / -1;
	}

	.fd-card-title {
		font-size: 14px;
		font-weight: 700;
		color: #1d293d;
		margin-bottom: 16px;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.fd-card-header-row {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 16px;
	}

	.fd-card-header-row .fd-card-title {
		margin-bottom: 0;
	}

	.fd-subtitle {
		font-size: 12px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: #62748e;
		margin: 20px 0 12px;
	}

	.fd-meta-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 8px 24px;
	}

	.fd-kv {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 6px 0;
		font-size: 13px;
		border-bottom: 1px solid #f1f5f9;
	}

	.fd-k {
		color: #62748e;
		font-weight: 500;
	}

	.fd-v {
		font-weight: 600;
		color: #1d293d;
	}

	.fd-fee-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 4px 24px;
	}

	.fd-expense-ex {
		display: flex;
		gap: 16px;
		margin-top: 16px;
		padding-top: 12px;
		border-top: 1px solid #f1f5f9;
		font-size: 12px;
		color: #62748e;
		flex-wrap: wrap;
	}

	.fd-return-cards {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 16px;
	}

	.fd-return-card {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 4px;
		padding: 20px;
		background: #f8fafc;
		border-radius: 12px;
		border: 1px solid #e2e8f0;
	}

	.fd-return-label {
		font-size: 11px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: #62748e;
	}

	.fd-return-value {
		font-size: 24px;
		font-weight: 800;
		color: #1d293d;
	}

	.fd-returns-table {
		max-height: 300px;
		overflow-y: auto;
	}

	.fd-returns-table table {
		width: 100%;
		border-collapse: collapse;
		font-size: 13px;
	}

	.fd-returns-table th,
	.fd-returns-table td {
		padding: 6px 12px;
		text-align: left;
		border-bottom: 1px solid #f1f5f9;
	}

	.fd-returns-table th {
		font-weight: 600;
		color: #62748e;
		font-size: 11px;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.fd-positive { color: #059669; }
	.fd-negative { color: #dc2626; }

	/* Tables */
	.fd-table-wrap {
		overflow-x: auto;
	}

	.fd-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 13px;
	}

	.fd-table th,
	.fd-table td {
		padding: 10px 12px;
		text-align: left;
		border-bottom: 1px solid #f1f5f9;
		white-space: nowrap;
	}

	.fd-table th {
		font-weight: 600;
		color: #62748e;
		font-size: 11px;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		position: sticky;
		top: 0;
		background: white;
	}

	.fd-table tbody tr:hover {
		background: #f8fafc;
	}

	.fd-num { text-align: right; font-variant-numeric: tabular-nums; }

	.fd-fund-name {
		max-width: 280px;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.fd-rank {
		color: #90a1b9;
		font-weight: 600;
		font-size: 12px;
	}

	.fd-select {
		height: 36px;
		padding: 0 10px;
		border: 1px solid #e2e8f0;
		border-radius: 10px;
		background: #f8fafc;
		font-size: 13px;
		color: var(--ii-text-primary);
		font-family: var(--ii-font-sans);
	}

	/* Percentile cards */
	.fd-pctile-grid {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: 16px;
	}

	.fd-pctile-card {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 4px;
		padding: 20px 16px;
		background: #f8fafc;
		border: 1px solid #e2e8f0;
		border-radius: 12px;
	}

	.fd-pctile-label {
		font-size: 11px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: #62748e;
	}

	.fd-pctile-value {
		font-size: 28px;
		font-weight: 800;
	}

	.fd-pctile-note {
		font-size: 10px;
		color: #90a1b9;
	}

	/* Holders summary */
	.fd-holder-summary {
		display: flex;
		gap: 32px;
		margin-bottom: 20px;
	}

	.fd-holder-stat {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.fd-holder-val {
		font-size: 24px;
		font-weight: 800;
		color: #1d293d;
	}

	.fd-holder-lbl {
		font-size: 11px;
		font-weight: 600;
		color: #62748e;
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}

	.fd-empty {
		color: #90a1b9;
		font-size: 13px;
		text-align: center;
		padding: 32px 16px;
	}

	.fd-empty-section {
		background: white;
		border: 1px solid #e2e8f0;
		border-radius: 16px;
		padding: 48px 24px;
		text-align: center;
	}

	@media (max-width: 768px) {
		.fd-grid {
			grid-template-columns: 1fr;
		}
		.fd-meta-grid,
		.fd-fee-grid {
			grid-template-columns: 1fr;
		}
		.fd-pctile-grid {
			grid-template-columns: repeat(2, 1fr);
		}
		.fd-return-cards {
			grid-template-columns: 1fr;
		}
	}
</style>
