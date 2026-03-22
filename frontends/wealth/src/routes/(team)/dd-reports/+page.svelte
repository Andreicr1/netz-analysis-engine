<!--
  DD Reports — select fund, trigger report generation, view existing reports.
-->
<script lang="ts">
	import { PageHeader, SectionCard, EmptyState, Button, Select } from "@netz/ui";
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

	const breadcrumbs = [
		{ label: "Screener", href: "/screener?tab=funds" },
		{ label: "DD Reports" },
	];
</script>

<div class="space-y-(--netz-space-section-gap) p-(--netz-space-page-gutter)">
	<PageHeader title="Due Diligence Reports" {breadcrumbs} />

	<SectionCard title="Select Fund">
		{#if funds.length > 0}
			<div class="flex items-center gap-3">
				<Select
					bind:value={selectedFundId}
					placeholder="Choose a fund..."
					options={funds.map((f) => ({ value: f.id, label: `${f.name}${f.ticker ? ` (${f.ticker})` : ""}` }))}
					searchable
					class="flex-1"
				/>
				<Button onclick={viewReports} disabled={!selectedFundId}>
					View Reports
				</Button>
			</div>
		{:else}
			<EmptyState title="No Funds" message="Add funds to generate due diligence reports." />
		{/if}
	</SectionCard>
</div>
