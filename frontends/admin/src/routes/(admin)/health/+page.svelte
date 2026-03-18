<!--
  Health Dashboard — System health monitoring with live worker logs.
  Auto-refresh via client-side $effect (NOT invalidateAll).
-->
<script lang="ts">
	import { SectionCard, MetricCard, StatusBadge, formatDate } from "@netz/ui";
	import ServiceHealthCard from "$lib/components/ServiceHealthCard.svelte";
	import WorkerLogFeed from "$lib/components/WorkerLogFeed.svelte";
	import { createClientApiClient } from "$lib/api/client";

	type HealthService = {
		name: string;
		status: string;
		latency_ms: number | null;
		error: string | null;
		checked_at?: string | null;
	};

	type HealthWorker = {
		name: string;
		status: string;
		last_run: string | null;
		duration_ms: number | null;
		error_count: number;
	};

	type HealthPipeline = {
		docs_processed: number;
		queue_depth: number;
		error_rate: number;
		checked_at?: string | null;
	};

	type HealthSectionErrors = {
		services: string | null;
		workers: string | null;
		pipelines: string | null;
	};

	type HealthPageData = {
		token: string;
		services: HealthService[];
		workers: HealthWorker[];
		pipelines: HealthPipeline;
		sectionErrors: HealthSectionErrors;
		hasDegradedState: boolean;
	};

	let { data }: { data: HealthPageData } = $props();

	// Client-side auto-refresh (NOT invalidateAll — avoids full SSR round trip)
	let healthData = $state(data.services);
	let pipelineData = $state(data.pipelines);
	let healthErrors = $derived(data.sectionErrors);
	let hasDegradedState = $derived(data.hasDegradedState);
	let degradedMessage = $derived(
		healthErrors.services || healthErrors.workers || healthErrors.pipelines
			? "Some health sections failed to load. Showing partial results."
			: hasDegradedState
				? "System health is degraded. Review the flagged services below."
				: null,
	);

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

	{#if degradedMessage}
		<div
			class="rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900"
			role="alert"
		>
			<p class="font-medium">Degraded state</p>
			<p class="mt-1">{degradedMessage}</p>
		</div>
	{/if}

	<!-- Service Health Grid -->
	<SectionCard title="Service Health">
		{#if healthErrors.services}
			<div
				class="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900"
				role="alert"
			>
				<p class="font-medium">Service health unavailable</p>
				<p class="mt-1">{healthErrors.services}</p>
			</div>
		{:else if healthData.length > 0}
			<div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
				{#each healthData as service}
					<ServiceHealthCard {service} />
				{/each}
			</div>
		{:else}
			<div class="rounded-lg border border-dashed border-[var(--netz-border)] px-4 py-3 text-sm text-[var(--netz-text-muted)]">
				No service health data available.
			</div>
		{/if}
	</SectionCard>

	<!-- Pipeline Stats -->
	<SectionCard title="Pipeline Stats">
		{#if healthErrors.pipelines}
			<div
				class="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900"
				role="alert"
			>
				<p class="font-medium">Pipeline stats unavailable</p>
				<p class="mt-1">{healthErrors.pipelines}</p>
			</div>
		{:else}
			<div class="grid grid-cols-1 gap-4 sm:grid-cols-3">
				<MetricCard label="Docs Processed" value={String(pipelineData.docs_processed ?? 0)} />
				<MetricCard label="Queue Depth" value={String(pipelineData.queue_depth ?? 0)} />
				<MetricCard
					label="Error Rate"
					value={`${((pipelineData.error_rate ?? 0) * 100).toFixed(1)}%`}
				/>
			</div>
			{#if pipelineData.checked_at}
				<p class="mt-3 text-xs text-[var(--netz-text-muted)]">
					Checked at
					<time datetime={pipelineData.checked_at}>
						{formatDate(pipelineData.checked_at, "medium", "en-US")}
					</time>
				</p>
			{/if}
		{/if}
	</SectionCard>

	<!-- Worker Status Table -->
	<SectionCard title="Workers">
		{#if healthErrors.workers}
			<div
				class="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900"
				role="alert"
			>
				<p class="font-medium">Worker status unavailable</p>
				<p class="mt-1">{healthErrors.workers}</p>
			</div>
		{:else if data.workers.length > 0}
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
