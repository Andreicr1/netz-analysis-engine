<!-- Fund Details tab — fetches prospectus fees/returns + manager team + brochure key sections.
     Lazy-loaded when the "Fund Details" tab is activated in CatalogDetailPanel. -->
<script lang="ts">
	import "./screener.css";
	import { formatPercent, formatNumber } from "@investintell/ui";

	interface ProspectusExpenseExamples {
		"1y": number | null;
		"3y": number | null;
		"5y": number | null;
		"10y": number | null;
	}

	interface ProspectusFees {
		expense_ratio_pct: number | null;
		net_expense_ratio_pct: number | null;
		management_fee_pct: number | null;
		fee_waiver_pct: number | null;
		distribution_12b1_pct: number | null;
		portfolio_turnover_pct: number | null;
		expense_examples: ProspectusExpenseExamples | null;
	}

	interface AnnualReturnItem {
		year: number;
		annual_return_pct: number | null;
	}

	interface AvgAnnualReturns {
		"1y": number | null;
		"5y": number | null;
		"10y": number | null;
	}

	interface ProspectusData {
		series_id: string | null;
		filing_date: string | null;
		fees: ProspectusFees;
		annual_returns: AnnualReturnItem[];
		avg_annual_returns: AvgAnnualReturns;
	}

	interface TeamMember {
		person_name: string;
		title: string | null;
		role: string | null;
		certifications: string[] | null;
		years_experience: number | null;
		bio_summary: string | null;
	}

	interface ManagerProfile {
		firm_name: string;
		team: TeamMember[];
	}

	interface BrochureSection {
		section: string;
		content: string;
		filing_date: string | null;
	}

	interface BrochureData {
		crd_number: string;
		sections: Record<string, BrochureSection>;
	}

	type ApiClient = { get: <T>(url: string, params?: Record<string, string>) => Promise<T> };

	let {
		api,
		cik,
		managerId,
	}: {
		api: ApiClient;
		cik: string | null;
		managerId: string | null;
	} = $props();

	let prospectus = $state<ProspectusData | null>(null);
	let team = $state<TeamMember[]>([]);
	let brochure = $state<Record<string, BrochureSection>>({});
	let loading = $state(true);
	let error = $state<string | null>(null);

	const SECTION_LABELS: Record<string, string> = {
		item_5: "Fees & Compensation",
		item_8: "Methods of Analysis & Investment Strategies",
		item_9: "Disciplinary Information",
		item_10: "Other Financial Industry Activities",
	};

	async function fetchAll() {
		loading = true;
		error = null;

		const promises: Promise<void>[] = [];

		if (cik) {
			promises.push(
				api.get<ProspectusData>(`/sec/funds/${cik}/prospectus`).then((d) => {
					prospectus = d;
				}).catch(() => {
					prospectus = null;
				}),
			);
		}

		if (managerId) {
			promises.push(
				api.get<ManagerProfile>(`/manager-screener/managers/${managerId}/profile`).then((d) => {
					team = d.team ?? [];
				}).catch(() => {
					team = [];
				}),
			);
			promises.push(
				api.get<BrochureData>(`/manager-screener/managers/${managerId}/brochure/key-sections`).then((d) => {
					brochure = d.sections ?? {};
				}).catch(() => {
					brochure = {};
				}),
			);
		}

		await Promise.all(promises);

		if (!prospectus && team.length === 0 && Object.keys(brochure).length === 0) {
			error = "No detailed data available for this fund.";
		}
		loading = false;
	}

	$effect(() => {
		if (cik || managerId) {
			fetchAll();
		} else {
			loading = false;
			error = "No fund or manager identifier available.";
		}
	});

	function fmtPct(v: number | null | undefined): string {
		if (v == null) return "\u2014";
		return formatPercent(v / 100);
	}

	function fmtDollar(v: number | null | undefined): string {
		if (v == null) return "\u2014";
		return `$${formatNumber(v)}`;
	}

	// Bar chart: scale returns to max absolute value
	let maxAbsReturn = $derived.by(() => {
		if (!prospectus?.annual_returns.length) return 10;
		const vals = prospectus.annual_returns
			.map((r) => Math.abs(r.annual_return_pct ?? 0))
			.filter((v) => v > 0);
		return vals.length > 0 ? Math.max(...vals) : 10;
	});
</script>

<div class="cdp-tab-content">
	{#if loading}
		<div class="dt-loading">Loading fund details\u2026</div>
	{:else if error && !prospectus && team.length === 0 && Object.keys(brochure).length === 0}
		<div class="cdp-na-section">
			<span class="cdp-na-badge">Fund Details N/A</span>
			<p class="cdp-na-text">{error}</p>
		</div>
	{:else}
		<!-- Prospectus Fee Table -->
		{#if prospectus}
			<div class="dt-section">
				<h4 class="dt-section-title">
					Fee Structure (SEC Prospectus)
					{#if prospectus.filing_date}
						<span class="dt-section-date">Filed {prospectus.filing_date}</span>
					{/if}
				</h4>
				<div class="fdt-fee-grid">
					{#if prospectus.fees.expense_ratio_pct != null}
						<div class="dt-kv"><span class="dt-k">Gross Expense Ratio</span><span class="dt-v">{fmtPct(prospectus.fees.expense_ratio_pct)}</span></div>
					{/if}
					{#if prospectus.fees.net_expense_ratio_pct != null}
						<div class="dt-kv"><span class="dt-k">Net Expense Ratio</span><span class="dt-v">{fmtPct(prospectus.fees.net_expense_ratio_pct)}</span></div>
					{/if}
					{#if prospectus.fees.management_fee_pct != null}
						<div class="dt-kv"><span class="dt-k">Management Fee</span><span class="dt-v">{fmtPct(prospectus.fees.management_fee_pct)}</span></div>
					{/if}
					{#if prospectus.fees.distribution_12b1_pct != null}
						<div class="dt-kv"><span class="dt-k">12b-1 Distribution Fee</span><span class="dt-v">{fmtPct(prospectus.fees.distribution_12b1_pct)}</span></div>
					{/if}
					{#if prospectus.fees.fee_waiver_pct != null}
						<div class="dt-kv"><span class="dt-k">Fee Waiver</span><span class="dt-v">{fmtPct(prospectus.fees.fee_waiver_pct)}</span></div>
					{/if}
					{#if prospectus.fees.portfolio_turnover_pct != null}
						<div class="dt-kv"><span class="dt-k">Portfolio Turnover</span><span class="dt-v">{fmtPct(prospectus.fees.portfolio_turnover_pct)}</span></div>
					{/if}
				</div>
				{#if prospectus.fees.expense_examples}
					<h4 class="dt-section-title fdt-subsection">Expense on $10,000 Investment</h4>
					<div class="fdt-fee-grid">
						<div class="dt-kv"><span class="dt-k">1 Year</span><span class="dt-v">{fmtDollar(prospectus.fees.expense_examples["1y"])}</span></div>
						<div class="dt-kv"><span class="dt-k">3 Years</span><span class="dt-v">{fmtDollar(prospectus.fees.expense_examples["3y"])}</span></div>
						<div class="dt-kv"><span class="dt-k">5 Years</span><span class="dt-v">{fmtDollar(prospectus.fees.expense_examples["5y"])}</span></div>
						<div class="dt-kv"><span class="dt-k">10 Years</span><span class="dt-v">{fmtDollar(prospectus.fees.expense_examples["10y"])}</span></div>
					</div>
				{/if}
			</div>

			<!-- Average Annual Returns -->
			{#if prospectus.avg_annual_returns["1y"] != null || prospectus.avg_annual_returns["5y"] != null || prospectus.avg_annual_returns["10y"] != null}
				<div class="dt-section">
					<h4 class="dt-section-title">Average Annual Returns</h4>
					<div class="fdt-fee-grid">
						{#if prospectus.avg_annual_returns["1y"] != null}
							<div class="dt-kv"><span class="dt-k">1 Year</span><span class="dt-v">{fmtPct(prospectus.avg_annual_returns["1y"])}</span></div>
						{/if}
						{#if prospectus.avg_annual_returns["5y"] != null}
							<div class="dt-kv"><span class="dt-k">5 Years</span><span class="dt-v">{fmtPct(prospectus.avg_annual_returns["5y"])}</span></div>
						{/if}
						{#if prospectus.avg_annual_returns["10y"] != null}
							<div class="dt-kv"><span class="dt-k">10 Years</span><span class="dt-v">{fmtPct(prospectus.avg_annual_returns["10y"])}</span></div>
						{/if}
					</div>
				</div>
			{/if}

			<!-- Annual Returns Bar Chart -->
			{#if prospectus.annual_returns.length > 0}
				<div class="dt-section">
					<h4 class="dt-section-title">Calendar Year Returns</h4>
					<div class="fdt-bar-chart">
						{#each prospectus.annual_returns as ret (ret.year)}
							{@const pct = ret.annual_return_pct ?? 0}
							{@const isNeg = pct < 0}
							{@const barWidth = Math.abs(pct) / maxAbsReturn * 50}
							<div class="fdt-bar-row">
								<span class="fdt-bar-year">{ret.year}</span>
								<div class="fdt-bar-track">
									{#if isNeg}
										<div class="fdt-bar-neg" style="width: {barWidth}%"></div>
										<div class="fdt-bar-center"></div>
									{:else}
										<div class="fdt-bar-center"></div>
										<div class="fdt-bar-pos" style="width: {barWidth}%"></div>
									{/if}
								</div>
								<span class="fdt-bar-val" class:fdt-bar-val--neg={isNeg}>
									{fmtPct(pct)}
								</span>
							</div>
						{/each}
					</div>
				</div>
			{/if}
		{/if}

		<!-- Management Team -->
		{#if team.length > 0}
			<div class="dt-section">
				<h4 class="dt-section-title">Management Team</h4>
				{#each team as member (member.person_name)}
					<div class="fdt-team-member">
						<div class="fdt-team-name">{member.person_name}</div>
						<div class="fdt-team-meta">
							{#if member.title}<span>{member.title}</span>{/if}
							{#if member.years_experience}<span>{member.years_experience}y experience</span>{/if}
							{#if member.certifications?.length}
								<span class="fdt-certs">{member.certifications.join(", ")}</span>
							{/if}
						</div>
						{#if member.bio_summary}
							<p class="fdt-team-bio">{member.bio_summary}</p>
						{/if}
					</div>
				{/each}
			</div>
		{/if}

		<!-- Brochure Key Sections -->
		{#if Object.keys(brochure).length > 0}
			{#each Object.entries(brochure) as [key, section] (key)}
				<div class="dt-section">
					<h4 class="dt-section-title">
						{SECTION_LABELS[key] ?? key}
						{#if section.filing_date}
							<span class="dt-section-date">{section.filing_date}</span>
						{/if}
					</h4>
					<div class="dt-brochure-text">{section.content}</div>
				</div>
			{/each}
		{/if}
	{/if}
</div>

<style>
	/* Fee grid */
	.fdt-fee-grid {
		display: flex;
		flex-direction: column;
	}

	.fdt-subsection {
		margin-top: 12px;
	}

	/* Bar chart */
	.fdt-bar-chart {
		display: flex;
		flex-direction: column;
		gap: 3px;
	}

	.fdt-bar-row {
		display: flex;
		align-items: center;
		gap: 8px;
		height: 22px;
	}

	.fdt-bar-year {
		width: 36px;
		font-size: 11px;
		font-weight: 600;
		color: var(--ii-text-muted);
		text-align: right;
		font-variant-numeric: tabular-nums;
		flex-shrink: 0;
	}

	.fdt-bar-track {
		flex: 1;
		display: flex;
		align-items: center;
		height: 14px;
		position: relative;
	}

	.fdt-bar-center {
		width: 1px;
		height: 14px;
		background: var(--ii-border);
		flex-shrink: 0;
	}

	.fdt-bar-pos {
		height: 14px;
		background: var(--ii-success);
		border-radius: 0 3px 3px 0;
		min-width: 2px;
		transition: width 300ms ease;
	}

	.fdt-bar-neg {
		height: 14px;
		background: var(--ii-danger);
		border-radius: 3px 0 0 3px;
		min-width: 2px;
		margin-left: auto;
		transition: width 300ms ease;
	}

	.fdt-bar-val {
		width: 52px;
		font-size: 11px;
		font-weight: 600;
		color: var(--ii-success);
		text-align: right;
		font-variant-numeric: tabular-nums;
		flex-shrink: 0;
	}

	.fdt-bar-val--neg {
		color: var(--ii-danger);
	}

	/* Team members */
	.fdt-team-member {
		padding: 8px 0;
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.fdt-team-member:last-child {
		border-bottom: none;
	}

	.fdt-team-name {
		font-size: 13px;
		font-weight: 600;
		color: var(--ii-text-primary);
	}

	.fdt-team-meta {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		font-size: 12px;
		color: var(--ii-text-secondary);
		margin-top: 2px;
	}

	.fdt-certs {
		font-weight: 600;
		color: var(--ii-brand-primary);
	}

	.fdt-team-bio {
		font-size: 12px;
		color: var(--ii-text-muted);
		line-height: 1.5;
		margin-top: 4px;
	}
</style>
