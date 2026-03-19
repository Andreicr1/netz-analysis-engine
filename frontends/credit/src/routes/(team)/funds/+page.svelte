<!--
  Fund selector page — shown when multiple funds exist.
  Redirects to first fund automatically if only one.
-->
<script lang="ts">
	import { Card, EmptyState, PageHeader, StatusBadge } from "@netz/ui";
	import { resolveCreditStatus } from "$lib/utils/status-maps";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();
</script>

<div class="px-6">
	<PageHeader title="Funds" />

	{#if data.funds.length === 0}
		<EmptyState
			title="No Funds"
			description="No funds are available for your organization. Contact your administrator."
		/>
	{:else}
		<div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
			{#each data.funds as fund (fund.id)}
				<a href="/funds/{fund.id}/pipeline" class="group block">
					<Card class="p-5 transition-[shadow,border-color] hover:shadow-md hover:border-(--netz-brand-primary)/30">
						<div class="flex items-start justify-between">
							<div class="min-w-0 flex-1">
								<h2 class="text-base font-semibold text-(--netz-text-primary) group-hover:text-(--netz-brand-primary) transition-colors">{fund.name}</h2>
								<div class="mt-2">
									<StatusBadge status={fund.status} type="default" resolve={resolveCreditStatus} />
								</div>
							</div>
							<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="mt-1 shrink-0 text-(--netz-text-muted) transition-transform group-hover:translate-x-0.5">
								<path d="m9 18 6-6-6-6"/>
							</svg>
						</div>
					</Card>
				</a>
			{/each}
		</div>
	{/if}
</div>
