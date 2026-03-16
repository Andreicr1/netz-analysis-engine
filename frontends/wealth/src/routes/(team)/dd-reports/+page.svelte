<!--
  DD Reports — select fund, trigger report generation, view existing reports.
-->
<script lang="ts">
	import { PageHeader, EmptyState, Button } from "@netz/ui";
	import type { PageData } from "./$types";
	import { goto } from "$app/navigation";

	let { data }: { data: PageData } = $props();

	type Fund = {
		id: string;
		name: string;
		ticker: string | null;
	};

	let funds = $derived((data.funds ?? []) as Fund[]);
	let selectedFundId = $state("");

	function viewReports() {
		if (selectedFundId) {
			goto(`/dd-reports/${selectedFundId}`);
		}
	}
</script>

<div class="space-y-6 p-6">
	<PageHeader title="Due Diligence Reports" />

	<div class="rounded-lg border border-[var(--netz-border)] bg-white p-5">
		<h3 class="mb-4 text-sm font-semibold text-[var(--netz-text-primary)]">Select Fund</h3>
		{#if funds.length > 0}
			<div class="flex items-center gap-3">
				<select
					class="flex-1 rounded-md border border-[var(--netz-border)] bg-white px-3 py-2 text-sm"
					bind:value={selectedFundId}
				>
					<option value="">Choose a fund...</option>
					{#each funds as fund (fund.id)}
						<option value={fund.id}>
							{fund.name} {fund.ticker ? `(${fund.ticker})` : ""}
						</option>
					{/each}
				</select>
				<Button onclick={viewReports} disabled={!selectedFundId}>
					View Reports
				</Button>
			</div>
		{:else}
			<EmptyState title="No Funds" message="Add funds to generate due diligence reports." />
		{/if}
	</div>
</div>
