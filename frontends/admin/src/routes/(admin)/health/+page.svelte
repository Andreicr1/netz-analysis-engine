<!--
  Health Dashboard — System health monitoring with live worker logs.
  Auto-refresh via client-side $effect (NOT invalidateAll).
-->
<script lang="ts">
	import { SectionCard, MetricCard, StatusBadge } from "@netz/ui";
	import type { PageData } from "./$types";
	import ServiceHealthCard from "$lib/components/ServiceHealthCard.svelte";
	import WorkerLogFeed from "$lib/components/WorkerLogFeed.svelte";
	import { createClientApiClient } from "$lib/api/client";

	let { data }: { data: PageData } = $props();

	// Client-side auto-refresh (NOT invalidateAll — avoids full SSR round trip)
	let healthData = $state(data.services);
	let pipelineData = $state(data.pipelines);

	$effect(() => {
		const interval = setInterval(async () => {
			try {
				const api = createClientApiClient(() => Promise.resolve(data.token));
				healthData = await api.get("/admin/health/services");
				pipelineData = await api.get("/admin/health/pipelines");
			} catch {
				/* silent refresh failure */
			}
		}, 30_000);
		return () => clearInterval(interval);
	});
</script>

<div class="space-y-6 p-6">
	<h1 class="text-2xl font-bold text-[var(--netz-text-primary)]">System Health</h1>

	<!-- Service Health Grid -->
	<div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
		{#each healthData as service}
			<ServiceHealthCard {service} />
		{/each}
		{#if healthData.length === 0}
			<div class="col-span-full text-center text-[var(--netz-text-muted)]">
				No service health data available.
			</div>
		{/if}
	</div>

	<!-- Pipeline Stats -->
	<SectionCard title="Pipeline Stats">
		<div class="grid grid-cols-1 gap-4 sm:grid-cols-3">
			<MetricCard label="Docs Processed" value={String(pipelineData.docs_processed ?? 0)} />
			<MetricCard label="Queue Depth" value={String(pipelineData.queue_depth ?? 0)} />
			<MetricCard
				label="Error Rate"
				value={`${((pipelineData.error_rate ?? 0) * 100).toFixed(1)}%`}
			/>
		</div>
	</SectionCard>

	<!-- Worker Status Table -->
	<SectionCard title="Workers">
		{#if data.workers.length > 0}
			<div class="overflow-x-auto">
				<table class="w-full text-left text-sm">
					<thead>
						<tr class="border-b border-[var(--netz-border)] text-[var(--netz-text-muted)]">
							<th class="pb-2 pr-4 font-medium">Worker</th>
							<th class="pb-2 pr-4 font-medium">Status</th>
							<th class="pb-2 pr-4 font-medium">Last Run</th>
							<th class="pb-2 pr-4 font-medium">Duration</th>
							<th class="pb-2 font-medium">Errors</th>
						</tr>
					</thead>
					<tbody>
						{#each data.workers as worker}
							<tr class="border-b border-[var(--netz-border)]">
								<td class="py-2 pr-4 text-[var(--netz-text-primary)]">{worker.name}</td>
								<td class="py-2 pr-4">
									<StatusBadge
										status={worker.status === "ok"
											? "low"
											: worker.status === "error"
												? "critical"
												: "medium"}
										type="risk"
									/>
								</td>
								<td class="py-2 pr-4 text-[var(--netz-text-secondary)]">
									{worker.last_run ?? "Never"}
								</td>
								<td class="py-2 pr-4 text-[var(--netz-text-secondary)]">
									{worker.duration_ms ? `${worker.duration_ms}ms` : "\u2014"}
								</td>
								<td class="py-2 text-[var(--netz-text-secondary)]">
									{worker.error_count}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{:else}
			<p class="text-[var(--netz-text-muted)]">No workers registered.</p>
		{/if}
	</SectionCard>

	<!-- Worker Log Feed -->
	<SectionCard title="Worker Logs">
		<WorkerLogFeed token={data.token} />
	</SectionCard>
</div>
