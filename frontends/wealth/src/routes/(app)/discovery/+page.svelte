<!--
  Discovery page — 3-column FCL orchestrator.

  Col1: Managers table (full-width in expand-1, compact in expand-2/3).
  Col2: Funds table for selected manager with inline DD/FS/Analysis buttons.
  Col3: Quick-read panel (FactSheet or DDReview). Heavy analytics live in
        the standalone /discovery/funds/{id}/analysis page.

  All state is URL-driven via `useDiscoveryUrlState()` — no localStorage.
-->
<script lang="ts">
	import { FlexibleColumnLayout, type FCLRatios } from "@investintell/ui";
	import { getContext } from "svelte";
	import { useDiscoveryUrlState } from "$lib/discovery/fcl-state.svelte";
	import { fetchFundsByManager } from "$lib/discovery/api";
	import DiscoveryManagersTable from "$lib/components/discovery/DiscoveryManagersTable.svelte";
	import DiscoveryFundsTable from "$lib/components/discovery/DiscoveryFundsTable.svelte";
	import FactSheetPanel from "$lib/components/discovery/col3/FactSheetPanel.svelte";
	import DDReviewPanel from "$lib/components/discovery/col3/DDReviewPanel.svelte";
	import type {
		ManagerRow,
		FundRowView,
	} from "$lib/components/discovery/columns";

	let { data } = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const fcl = useDiscoveryUrlState();

	let managers = $state<ManagerRow[]>(
		(data.initialManagers ?? []) as ManagerRow[],
	);
	let funds = $state<FundRowView[]>([]);
	let fundsError = $state<string | null>(null);

	const SCREENER_RATIOS: FCLRatios = {
		"expand-1": [1, 0, 0],
		"expand-2": [0.32, 0.68, 0],
		"expand-3": [0.22, 0.42, 0.36],
	};

	// Lazy-load funds when manager changes.
	$effect(() => {
		const mid = fcl.managerId;
		if (!mid) {
			funds = [];
			return;
		}
		const ctrl = new AbortController();
		fundsError = null;
		fetchFundsByManager(getToken, mid, { limit: 100 }, ctrl.signal)
			.then((body) => {
				funds = (body.rows ?? []) as FundRowView[];
			})
			.catch((e: unknown) => {
				if ((e as Error).name !== "AbortError") {
					fundsError = (e as Error).message;
				}
			});
		return () => ctrl.abort();
	});
</script>

<svelte:head><title>Discovery — Netz Wealth</title></svelte:head>

{#if data.status === "error"}
	<div class="col-error">Failed to load managers: {data.error}</div>
{:else}
	<FlexibleColumnLayout
		state={fcl.state}
		ratios={SCREENER_RATIOS}
		column1Label="Managers"
		column2Label="Funds"
		column3Label="Fund Detail"
	>
		{#snippet column1()}
			<DiscoveryManagersTable
				rows={managers}
				compact={fcl.state !== "expand-1"}
				selectedId={fcl.managerId}
				onSelect={(id) => fcl.selectManager(id)}
			/>
		{/snippet}
		{#snippet column2()}
			{#if fundsError}
				<div class="col-error">Failed to load funds: {fundsError}</div>
			{:else if funds.length === 0 && fcl.managerId}
				<div class="col-loading">Loading funds…</div>
			{:else}
				<DiscoveryFundsTable
					rows={funds}
					selectedFundId={fcl.fundId}
					activeView={fcl.fundId ? fcl.view : null}
					onSelectCol3={(id, view) => fcl.selectFund(id, view)}
					onOpenAnalysis={(id) => fcl.openAnalysis(id, "returns-risk")}
				/>
			{/if}
		{/snippet}
		{#snippet column3()}
			{#if fcl.fundId}
				{#if fcl.view === "dd"}
					<DDReviewPanel fundId={fcl.fundId} />
				{:else}
					<FactSheetPanel fundId={fcl.fundId} />
				{/if}
			{/if}
		{/snippet}
	</FlexibleColumnLayout>
{/if}

<style>
	.col-error,
	.col-loading {
		padding: 24px;
		text-align: center;
		color: var(--ii-text-muted);
		font-family: "Urbanist", system-ui, sans-serif;
	}
	.col-error {
		color: var(--ii-error);
	}
</style>
