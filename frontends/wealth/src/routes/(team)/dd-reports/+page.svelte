<!--
  DD Reports — select fund, trigger report generation, view existing reports.
-->
<script lang="ts">
	import { PageHeader, SectionCard, EmptyState, Button } from "@netz/ui";
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

<div class="space-y-(--netz-space-section-gap) p-(--netz-space-page-gutter)">
	<PageHeader title="Due Diligence Reports" />

	<SectionCard title="Select Fund">
		{#if funds.length > 0}
			<div class="flex items-center gap-3">
				<select
					class="flex-1 rounded-md border border-(--netz-border) bg-(--netz-surface-elevated) px-3 py-2 text-sm"
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
	</SectionCard>
</div>
