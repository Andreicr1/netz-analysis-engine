<!--
  Disclosure-conditional detail panel for a UnifiedFundItem.
  Renders tabs based on DisclosureMatrix flags.
-->
<script lang="ts">
	import "./screener.css";
	import { getContext } from "svelte";
	import { goto } from "$app/navigation";
	import { Button } from "@investintell/ui/components/ui/button";
	import { StatusBadge, ConsequenceDialog, formatAUM, formatPercent } from "@investintell/ui";
	import type { ConsequenceDialogPayload } from "@investintell/ui";
	import { createClientApiClient } from "$lib/api/client";
	import type { UnifiedFundItem } from "$lib/types/catalog";
	import { UNIVERSE_LABELS } from "$lib/types/catalog";
	import SecHoldingsTable from "./SecHoldingsTable.svelte";
	import SecStyleDriftChart from "./SecStyleDriftChart.svelte";

	interface Props {
		fund: UnifiedFundItem;
	}

	let { fund }: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

	// Tabs driven by disclosure
	type DetailTab = "overview" | "holdings" | "style" | "quant";

	let activeTab = $state<DetailTab>("overview");

	let availableTabs = $derived.by(() => {
		const tabs: { key: DetailTab; label: string }[] = [{ key: "overview", label: "Overview" }];
		if (fund.disclosure.has_holdings) tabs.push({ key: "holdings", label: "Holdings" });
		if (fund.disclosure.has_style_analysis) tabs.push({ key: "style", label: "Style Drift" });
		if (fund.disclosure.has_quant_metrics) tabs.push({ key: "quant", label: "Quant Metrics" });
		return tabs;
	});

	// Reset tab when fund changes
	$effect(() => {
		if (fund) activeTab = "overview";
	});

	// ── CIK for holdings/style (registered funds use external_id as cik)
	let fundCik = $derived(
		fund.universe === "registered_us" ? fund.external_id : null
	);

	// ── Send to Review ──
	let reviewDialogOpen = $state(false);
	let sendingToReview = $state(false);
	let reviewError = $state<string | null>(null);

	async function handleSendToReview(payload: ConsequenceDialogPayload) {
		sendingToReview = true;
		reviewError = null;
		try {
			let instrumentId = fund.instrument_id;

			if (!instrumentId) {
				const identifier = fund.isin || fund.ticker;
				if (!identifier) {
					reviewError = "Cannot import: no ISIN or ticker available.";
					return;
				}
				const imported = await api.post<{ instrument_id: string }>(`/screener/import/${identifier}`, {});
				instrumentId = imported.instrument_id;
			}

			if (!instrumentId) {
				reviewError = "Cannot create DD report: instrument ID not available.";
				return;
			}

			const ddReport = await api.post<{ id: string }>(`/dd-reports/funds/${instrumentId}`, {});
			reviewDialogOpen = false;
			goto(`/dd-reports/${instrumentId}/${ddReport.id}`);
		} catch (e) {
			reviewError = e instanceof Error ? e.message : "Failed to send to review";
		} finally {
			sendingToReview = false;
		}
	}
</script>

<!-- Tabs -->
<div class="dt-tabs">
	{#each availableTabs as tab (tab.key)}
		<button
			class="dt-tab"
			class:dt-tab--active={activeTab === tab.key}
			onclick={() => (activeTab = tab.key)}
		>
			{tab.label}
		</button>
	{/each}
</div>

<div class="dt-content">
	{#if activeTab === "overview"}
		<!-- Identity -->
		<div class="dt-section">
			<div class="dt-header-row">
				<span class="univ-badge univ-badge--{fund.universe.split('_')[0]}">{UNIVERSE_LABELS[fund.universe]}</span>
				{#if fund.screening_status}
					<StatusBadge status={fund.screening_status} />
				{/if}
			</div>
			<div class="dt-fund-meta">
				{#if fund.ticker}<span>Ticker: {fund.ticker}</span>{/if}
				{#if fund.isin}<span>ISIN: {fund.isin}</span>{/if}
				{#if fund.manager_name}<span>Manager: {fund.manager_name}</span>{/if}
				{#if fund.aum != null}<span>AUM: {formatAUM(fund.aum, fund.currency ?? "USD")}</span>{/if}
				<span>Region: {fund.region}</span>
				<span>Type: {fund.fund_type.replace(/_/g, " ")}</span>
				{#if fund.domicile}<span>Domicile: {fund.domicile}</span>{/if}
				{#if fund.currency}<span>Currency: {fund.currency}</span>{/if}
				{#if fund.inception_date}<span>Inception: {fund.inception_date}</span>{/if}
				{#if fund.total_shareholder_accounts != null}<span>Shareholders: {fund.total_shareholder_accounts.toLocaleString()}</span>{/if}
				{#if fund.investor_count != null}<span>Investors: {fund.investor_count.toLocaleString()}</span>{/if}
			</div>
		</div>

		<!-- N-CEN Flags -->
		{#if fund.is_index || fund.is_target_date || fund.is_fund_of_fund}
			<div class="dt-ncen-flags">
				{#if fund.is_index}<span class="dt-ncen-badge">Index Fund</span>{/if}
				{#if fund.is_target_date}<span class="dt-ncen-badge">Target Date</span>{/if}
				{#if fund.is_fund_of_fund}<span class="dt-ncen-badge">Fund of Funds</span>{/if}
			</div>
		{/if}

		<!-- Cost & Performance -->
		{#if fund.expense_ratio_pct != null || fund.avg_annual_return_1y != null || fund.avg_annual_return_10y != null}
			<div class="dt-section">
				<h4 class="dt-section-title">Cost & Performance</h4>
				<div class="dt-fund-meta">
					{#if fund.expense_ratio_pct != null}<span>Expense Ratio: {Number(fund.expense_ratio_pct).toFixed(2)}%</span>{/if}
					{#if fund.avg_annual_return_1y != null}<span>1Y Return: {formatPercent(Number(fund.avg_annual_return_1y) / 100)}</span>{/if}
					{#if fund.avg_annual_return_10y != null}<span>10Y Return: {formatPercent(Number(fund.avg_annual_return_10y) / 100)}</span>{/if}
				</div>
			</div>
		{/if}

		<!-- Disclosure Matrix -->
		<div class="dt-section">
			<h4 class="dt-section-title">Data Availability</h4>
			<div class="cdp-matrix">
				<div class="cdp-matrix-row">
					<span class="cdp-matrix-label">Holdings</span>
					<span class="cdp-matrix-value" class:cdp-avail={fund.disclosure.has_holdings} class:cdp-unavail={!fund.disclosure.has_holdings}>
						{fund.disclosure.has_holdings ? (fund.disclosure.holdings_source === "nport" ? "Holdings Data" : "Portfolio Holdings") : "N/A"}
					</span>
				</div>
				<div class="cdp-matrix-row">
					<span class="cdp-matrix-label">NAV History</span>
					<span class="cdp-matrix-value" class:cdp-avail={fund.disclosure.has_nav_history} class:cdp-unavail={!fund.disclosure.has_nav_history}>
						{fund.disclosure.has_nav_history ? "Available" : "N/A"}
					</span>
				</div>
				<div class="cdp-matrix-row">
					<span class="cdp-matrix-label">Quant Metrics</span>
					<span class="cdp-matrix-value" class:cdp-avail={fund.disclosure.has_quant_metrics} class:cdp-unavail={!fund.disclosure.has_quant_metrics}>
						{fund.disclosure.has_quant_metrics ? "Available" : "N/A"}
					</span>
				</div>
				<div class="cdp-matrix-row">
					<span class="cdp-matrix-label">Style Analysis</span>
					<span class="cdp-matrix-value" class:cdp-avail={fund.disclosure.has_style_analysis} class:cdp-unavail={!fund.disclosure.has_style_analysis}>
						{fund.disclosure.has_style_analysis ? "Available" : "N/A"}
					</span>
				</div>
				<div class="cdp-matrix-row">
					<span class="cdp-matrix-label">Fund Details</span>
					<span class="cdp-matrix-value" class:cdp-avail={fund.disclosure.has_private_fund_data} class:cdp-unavail={!fund.disclosure.has_private_fund_data}>
						{fund.disclosure.has_private_fund_data ? "Available" : "N/A"}
					</span>
				</div>
				<div class="cdp-matrix-row">
					<span class="cdp-matrix-label">Institutional Holdings</span>
					<span class="cdp-matrix-value" class:cdp-avail={fund.disclosure.has_13f_overlay} class:cdp-unavail={!fund.disclosure.has_13f_overlay}>
						{fund.disclosure.has_13f_overlay ? "Linked" : "N/A"}
					</span>
				</div>
			</div>
		</div>

		<!-- Screening overlay -->
		{#if fund.screening_score != null}
			<div class="dt-section">
				<h4 class="dt-section-title">Screening</h4>
				<div class="dt-kv"><span class="dt-k">Score</span><span class="dt-v">{formatPercent(fund.screening_score)}</span></div>
				<div class="dt-kv"><span class="dt-k">Status</span><StatusBadge status={fund.screening_status ?? "\u2014"} /></div>
			</div>
		{/if}

		<!-- Actions -->
		<div class="dt-section">
			{#if !fund.instrument_id}
				<p class="dt-empty-text">This fund is not yet in your universe. Import and send to DD review.</p>
			{/if}
			<Button size="sm" onclick={() => reviewDialogOpen = true} disabled={sendingToReview}>
				{sendingToReview ? "Sending\u2026" : "Send to Review"}
			</Button>
			{#if reviewError}
				<span class="dt-add-error">{reviewError}</span>
			{/if}
		</div>

	{:else if activeTab === "holdings"}
		<div class="cdp-tab-content">
			{#if fund.disclosure.has_holdings && fundCik}
				<SecHoldingsTable {api} cik={fundCik} managerName={fund.name} />
			{:else}
				<div class="cdp-na-section">
					<span class="cdp-na-badge">Holdings N/A</span>
					<p class="cdp-na-text">This fund's universe ({UNIVERSE_LABELS[fund.universe]}) does not provide holdings disclosure.</p>
				</div>
			{/if}
		</div>

	{:else if activeTab === "style"}
		<div class="cdp-tab-content">
			{#if fund.disclosure.has_style_analysis && fundCik}
				<SecStyleDriftChart {api} cik={fundCik} managerName={fund.name} />
			{:else}
				<div class="cdp-na-section">
					<span class="cdp-na-badge">Style Analysis N/A</span>
					<p class="cdp-na-text">Style snapshots are available for US Registered funds with holdings disclosure.</p>
				</div>
			{/if}
		</div>

	{:else if activeTab === "quant"}
		<div class="cdp-tab-content">
			{#if fund.disclosure.has_quant_metrics}
				<div class="cdp-quant-placeholder">
					<p class="dt-empty-text">Quant metrics (CVaR, Sharpe, momentum) available after importing this fund to your universe.</p>
					{#if !fund.instrument_id}
						<Button size="sm" variant="outline" onclick={() => reviewDialogOpen = true}>
							Import & Analyze
						</Button>
					{/if}
				</div>
			{:else}
				<div class="cdp-na-section">
					<span class="cdp-na-badge">Quant Metrics N/A</span>
					<p class="cdp-na-text">Requires NAV history. This fund has no tradeable ticker.</p>
				</div>
			{/if}
		</div>
	{/if}
</div>

<!-- Send to Review dialog -->
<ConsequenceDialog
	bind:open={reviewDialogOpen}
	title="Send to DD Review"
	impactSummary={!fund.instrument_id
		? "This fund will be imported to your universe and a DD Report will be created for committee review."
		: "A DD Report will be created for this fund for committee review."}
	requireRationale={true}
	rationaleLabel="Review justification"
	rationalePlaceholder="Why should this fund undergo due diligence review? (min 10 chars)"
	rationaleMinLength={10}
	confirmLabel="Send to Review"
	metadata={[
		{ label: "Fund", value: fund.name },
		{ label: "Universe", value: UNIVERSE_LABELS[fund.universe] },
		{ label: "Ticker", value: fund.ticker ?? "\u2014" },
		{ label: "ISIN", value: fund.isin ?? "\u2014" },
	]}
	onConfirm={handleSendToReview}
/>

<style>
	.dt-content {
		overflow-y: auto;
		flex: 1;
	}

	.cdp-tab-content {
		padding: 16px;
	}

	/* N-CEN flags */
	.dt-ncen-flags { display: flex; gap: 6px; flex-wrap: wrap; padding: 0 16px 8px; }
	.dt-ncen-badge { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; background: color-mix(in srgb, var(--ii-info) 12%, transparent); color: var(--ii-info); }

	/* Universe badge inline */
	.univ-badge {
		display: inline-block;
		padding: 3px 8px;
		border-radius: 8px;
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.02em;
		white-space: nowrap;
	}
	.univ-badge--registered { background: #fff7ed; border: 1px solid #fed7aa; color: #c2410c; }
	.univ-badge--private { background: #fef2f2; border: 1px solid #fecaca; color: #dc2626; }
	.univ-badge--ucits { background: #ecfdf5; border: 1px solid #d0fae5; color: #007a55; }

	/* Disclosure matrix */
	.cdp-matrix {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.cdp-matrix-row {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 4px 0;
		font-size: 13px;
	}

	.cdp-matrix-label {
		color: var(--ii-text-muted);
	}

	.cdp-matrix-value {
		font-weight: 600;
		font-size: 12px;
	}

	.cdp-avail {
		color: #059669;
		background: #ecfdf5;
		padding: 2px 8px;
		border-radius: 6px;
	}

	.cdp-unavail {
		color: #90a1b9;
		background: #f1f5f9;
		padding: 2px 8px;
		border-radius: 6px;
	}

	/* N/A sections */
	.cdp-na-section {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 12px;
		padding: 48px 24px;
		text-align: center;
	}

	.cdp-na-badge {
		display: inline-block;
		padding: 6px 16px;
		border-radius: 10px;
		font-size: 12px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		background: #f1f5f9;
		color: #90a1b9;
		border: 1px solid #e2e8f0;
	}

	.cdp-na-text {
		color: var(--ii-text-muted);
		font-size: 13px;
		max-width: 320px;
		line-height: 1.5;
	}

	.cdp-quant-placeholder {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 16px;
		padding: 32px 24px;
		text-align: center;
	}
</style>
