<!--
  Manager filter sidebar — manager search, funnel, fund filters, last run.
-->
<script lang="ts">
	import "./screener.css";
	import { goto } from "$app/navigation";
	import { Button, StatusBadge, formatNumber, formatDateTime } from "@netz/ui";
	import type { ScreeningResult, ScreeningRun, ScreenerFilterConfig, OverallStatus } from "$lib/types/screening";
	import { EMPTY_FILTERS } from "$lib/types/screening";

	interface Props {
		results: ScreeningResult[];
		lastRun: ScreeningRun | null;
		runError: string | null;
		initParams: Record<string, string>;
		fundFilters: ScreenerFilterConfig;
		onRunClick?: () => void;
		runDetailOpen?: boolean;
		runDetailLoading?: boolean;
		runDetailData?: Record<string, unknown> | null;
	}

	let { results, lastRun, runError, initParams = {}, fundFilters = $bindable(), onRunClick, runDetailOpen = false, runDetailLoading = false, runDetailData = null }: Props = $props();

	// ── Manager filters ──
	let textSearch = $state(initParams.text_search ?? "");
	let aumMin = $state(initParams.aum_min ?? "");
	let aumMax = $state(initParams.aum_max ?? "");
	let complianceClean = $state(initParams.compliance_clean === "true");
	let hasInstitutional = $state(initParams.has_institutional_holders === "true");

	function applyManagerFilters() {
		const params = new URLSearchParams();
		params.set("mode", "managers");
		if (textSearch) params.set("text_search", textSearch);
		if (aumMin) params.set("aum_min", aumMin);
		if (aumMax) params.set("aum_max", aumMax);
		if (complianceClean) params.set("compliance_clean", "true");
		if (hasInstitutional) params.set("has_institutional_holders", "true");
		params.set("page", "1");
		params.set("page_size", "25");
		goto(`/screener?${params.toString()}`, { invalidateAll: true });
	}

	function clearManagerFilters() {
		textSearch = "";
		aumMin = "";
		aumMax = "";
		complianceClean = false;
		hasInstitutional = false;
		goto("/screener?mode=managers", { invalidateAll: true });
	}

	function handleFilterKeydown(e: KeyboardEvent) {
		if (e.key === "Enter") applyManagerFilters();
	}

	// ── Fund filter helpers ──
	function typeLabel(type: string | undefined): string {
		switch (type) {
			case "fund":   return "Fund";
			case "bond":   return "Fixed Income";
			case "equity": return "Equity";
			default:       return type ?? "—";
		}
	}

	let distinctTypes = $derived(
		[...new Set(results.map((r) => r.instrument_type).filter(Boolean))] as string[]
	);
	let distinctBlocks = $derived(
		[...new Set(results.map((r) => r.block_id).filter(Boolean))] as string[]
	);

	// Funnel counts
	let universeCount = $derived(results.length);
	let l1PassCount = $derived(results.filter((r) => r.failed_at_layer !== 1).length);
	let l2EligibleCount = $derived(
		results.filter((r) => r.failed_at_layer !== 1 && r.failed_at_layer !== 2).length
	);
	let passCount = $derived(results.filter((r) => r.overall_status === "PASS").length);
	let watchlistCount = $derived(results.filter((r) => r.overall_status === "WATCHLIST").length);
	let failCount = $derived(results.filter((r) => r.overall_status === "FAIL").length);

	function setStatusFilter(status: OverallStatus | null) {
		fundFilters.status = status;
	}

	function clearFundFilters() {
		fundFilters = { ...EMPTY_FILTERS };
	}

	const hasFundFilters = $derived(
		fundFilters.status !== null ||
		fundFilters.instrument_type !== null ||
		fundFilters.block_id !== null ||
		fundFilters.search !== ""
	);
</script>

<!-- Manager filters -->
<div class="scr-filter-section">
	<h3 class="scr-filter-title">Manager</h3>
	<div class="scr-field">
		<input class="scr-input" type="text" placeholder="Firm name…" bind:value={textSearch} onkeydown={handleFilterKeydown} />
	</div>
	<div class="scr-field-row">
		<input class="scr-input scr-input--half" type="number" placeholder="AUM min" bind:value={aumMin} onkeydown={handleFilterKeydown} />
		<input class="scr-input scr-input--half" type="number" placeholder="AUM max" bind:value={aumMax} onkeydown={handleFilterKeydown} />
	</div>
	<label class="scr-checkbox">
		<input type="checkbox" bind:checked={complianceClean} />
		<span>Compliance clean</span>
	</label>
	<label class="scr-checkbox">
		<input type="checkbox" bind:checked={hasInstitutional} />
		<span>Has institutional holders</span>
	</label>
	<div class="scr-filter-btns">
		<Button size="sm" onclick={applyManagerFilters}>Apply</Button>
		<Button size="sm" variant="ghost" onclick={clearManagerFilters}>Clear</Button>
	</div>
</div>

<!-- Fund screening funnel -->
<div class="scr-filter-section">
	<h3 class="scr-filter-title">Screening Funnel</h3>
	<div class="funnel">
		<div class="funnel-row">
			<span class="funnel-label">Universe</span>
			<span class="funnel-value">{universeCount}</span>
		</div>
		<div class="funnel-bar" style:--fill="100%"></div>

		<div class="funnel-row">
			<span class="funnel-label">L1 Passed</span>
			<span class="funnel-value">{l1PassCount}</span>
		</div>
		<div class="funnel-bar" style:--fill="{universeCount ? (l1PassCount / universeCount) * 100 : 0}%"></div>

		<div class="funnel-row">
			<span class="funnel-label">L2 Eligible</span>
			<span class="funnel-value">{l2EligibleCount}</span>
		</div>
		<div class="funnel-bar" style:--fill="{universeCount ? (l2EligibleCount / universeCount) * 100 : 0}%"></div>

		<div class="funnel-row funnel-row--outcomes">
			<button
				class="funnel-outcome"
				class:funnel-outcome--active={fundFilters.status === "PASS"}
				onclick={() => setStatusFilter(fundFilters.status === "PASS" ? null : "PASS")}
			>
				<span class="funnel-dot funnel-dot--pass"></span>
				<span>Pass</span>
				<span class="funnel-count">{passCount}</span>
			</button>
			<button
				class="funnel-outcome"
				class:funnel-outcome--active={fundFilters.status === "WATCHLIST"}
				onclick={() => setStatusFilter(fundFilters.status === "WATCHLIST" ? null : "WATCHLIST")}
			>
				<span class="funnel-dot funnel-dot--watchlist"></span>
				<span>Watch</span>
				<span class="funnel-count">{watchlistCount}</span>
			</button>
			<button
				class="funnel-outcome"
				class:funnel-outcome--active={fundFilters.status === "FAIL"}
				onclick={() => setStatusFilter(fundFilters.status === "FAIL" ? null : "FAIL")}
			>
				<span class="funnel-dot funnel-dot--fail"></span>
				<span>Fail</span>
				<span class="funnel-count">{failCount}</span>
			</button>
		</div>
	</div>
</div>

<!-- Fund filters -->
<div class="scr-filter-section">
	<h3 class="scr-filter-title">Fund Filters</h3>
	<div class="scr-field">
		<label class="scr-label" for="scr-fund-search">Search</label>
		<input
			id="scr-fund-search"
			type="text"
			class="scr-input"
			placeholder="Name, ISIN, ticker…"
			bind:value={fundFilters.search}
		/>
	</div>
	<div class="scr-field">
		<label class="scr-label" for="scr-fund-type">Instrument Type</label>
		<select id="scr-fund-type" class="scr-select" bind:value={fundFilters.instrument_type}>
			<option value={null}>All types</option>
			{#each distinctTypes as t (t)}
				<option value={t}>{typeLabel(t)}</option>
			{/each}
		</select>
	</div>
	<div class="scr-field">
		<label class="scr-label" for="scr-fund-block">Allocation Block</label>
		<select id="scr-fund-block" class="scr-select" bind:value={fundFilters.block_id}>
			<option value={null}>All blocks</option>
			{#each distinctBlocks as b (b)}
				<option value={b}>{b}</option>
			{/each}
		</select>
	</div>
	{#if hasFundFilters}
		<button class="scr-clear-btn" onclick={clearFundFilters}>Clear fund filters</button>
	{/if}
</div>

<!-- Last run -->
{#if lastRun}
	<div class="scr-filter-section scr-filter-section--meta">
		<h3 class="scr-filter-title">Last Run</h3>
		<div class="scr-meta-row">
			<span class="scr-meta-k">Status</span>
			<StatusBadge status={lastRun.status} />
		</div>
		<div class="scr-meta-row">
			<span class="scr-meta-k">Instruments</span>
			<span class="scr-meta-v">{formatNumber(lastRun.instrument_count)}</span>
		</div>
		<div class="scr-meta-row">
			<span class="scr-meta-k">Started</span>
			<span class="scr-meta-v">{formatDateTime(lastRun.started_at)}</span>
		</div>
		{#if lastRun.completed_at}
			<div class="scr-meta-row">
				<span class="scr-meta-k">Completed</span>
				<span class="scr-meta-v">{formatDateTime(lastRun.completed_at)}</span>
			</div>
		{/if}
		{#if onRunClick}
			<button class="scr-detail-toggle" onclick={onRunClick}>
				{runDetailOpen ? "Hide Details" : "View Details"}
			</button>
		{/if}
		{#if runDetailOpen}
			<div class="scr-run-detail">
				{#if runDetailLoading}
					<p class="scr-run-detail-msg">Loading…</p>
				{:else if runDetailData}
					{#each Object.entries(runDetailData) as [key, val] (key)}
						<div class="scr-meta-row">
							<span class="scr-meta-k">{key}</span>
							<span class="scr-meta-v">{typeof val === "object" ? JSON.stringify(val) : String(val ?? "—")}</span>
						</div>
					{/each}
				{:else}
					<p class="scr-run-detail-msg">No details available.</p>
				{/if}
			</div>
		{/if}
	</div>
{/if}

{#if runError}
	<div class="scr-filter-error">{runError}</div>
{/if}
