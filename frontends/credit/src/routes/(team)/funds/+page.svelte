<!--
  Fund selector page — shown when multiple funds exist.
  Redirects to first fund automatically if only one.
-->
<script lang="ts">
	import { Card, EmptyState } from "@netz/ui";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();
</script>

<div class="p-6">
	<h1 class="mb-6 text-2xl font-bold text-[var(--netz-text-primary)]">Select Fund</h1>

	{#if data.funds.length === 0}
		<EmptyState
			title="No Funds"
			description="No funds are available for your organization. Contact your administrator."
		/>
	{:else}
		<div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
			{#each data.funds as fund (fund.id)}
				<a href="/funds/{fund.id}/pipeline" class="block">
					<Card class="p-5 transition-shadow hover:shadow-md">
						<h2 class="text-lg font-semibold text-[var(--netz-text-primary)]">{fund.name}</h2>
						<p class="mt-1 text-sm text-[var(--netz-text-secondary)]">{fund.status}</p>
					</Card>
				</a>
			{/each}
		</div>
	{/if}
</div>
