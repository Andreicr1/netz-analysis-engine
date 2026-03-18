<!--
  Health Dashboard — System health monitoring with live worker logs.
  Auto-refresh via client-side $effect (NOT invalidateAll).
-->
<script lang="ts">
	import { DataTable, MetricCard, SectionCard, formatDateTime, formatNumber, formatPercent } from "@netz/ui";
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
	let workerStatusFilter = $state("all");
	let healthErrors = $derived(data.sectionErrors);
	let hasDegradedState = $derived(data.hasDegradedState);
	let degradedMessage = $derived(
		healthErrors.services || healthErrors.workers || healthErrors.pipelines
			? "Some health sections failed to load. Showing partial results."
			: hasDegradedState
				? "System health is degraded. Review the flagged services below."
			: null,
	);
	let workerStatusOptions = $derived(Array.from(new Set(data.workers.map((worker) => worker.status))).sort());
	let workerRows = $derived(
		workerStatusFilter === "all"
			? data.workers
			: data.workers.filter((worker) => worker.status === workerStatusFilter),
	);

	const workerColumns = [
		{
			accessorKey: "name",
			header: "Worker",
			cell: (info: any) => String(info.getValue() ?? ""),
		},
		{
			accessorKey: "status",
			header: "Status",
			cell: (info: any) => String(info.getValue() ?? ""),
		},
		{
			accessorKey: "last_run",
			header: "Last Run",
			cell: (info: any) => {
				const worker = info.row.original as HealthWorker;
				return worker.last_run ? formatDateTime(worker.last_run, "en-US") : "Never";
			},
		},
		{
			accessorKey: "duration_ms",
			header: "Duration",
			cell: (info: any) => {
				const worker = info.row.original as HealthWorker;
				return worker.duration_ms !== null ? `${formatNumber(worker.duration_ms, 0, "en-US")}ms` : "\u2014";
			},
		},
		{
			accessorKey: "error_count",
			header: "Errors",
			cell: (info: any) => String(info.getValue() ?? 0),
		},
	] as any;

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
			class="rounded-xl border px-4 py-3 text-sm"
			style="border-color: var(--netz-warning); background-color: color-mix(in srgb, var(--netz-warning) 12%, var(--netz-surface)); color: var(--netz-text-primary);"
			role="alert"
		>
			<p class="font-medium text-[var(--netz-warning)]">Degraded state</p>
			<p class="mt-1">{degradedMessage}</p>
		</div>
	{/if}

	<!-- Service Health Grid -->
	<SectionCard title="Service Health">
		{#if healthErrors.services}
			<div
				class="rounded-lg border px-4 py-3 text-sm"
				style="border-color: var(--netz-warning); background-color: color-mix(in srgb, var(--netz-warning) 12%, var(--netz-surface)); color: var(--netz-text-primary);"
				role="alert"
			>
				<p class="font-medium text-[var(--netz-warning)]">Service health unavailable</p>
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
				class="rounded-lg border px-4 py-3 text-sm"
				style="border-color: var(--netz-warning); background-color: color-mix(in srgb, var(--netz-warning) 12%, var(--netz-surface)); color: var(--netz-text-primary);"
				role="alert"
			>
				<p class="font-medium text-[var(--netz-warning)]">Pipeline stats unavailable</p>
				<p class="mt-1">{healthErrors.pipelines}</p>
			</div>
		{:else}
			<div class="grid grid-cols-1 gap-4 sm:grid-cols-3">
				<MetricCard label="Docs Processed" value={String(pipelineData.docs_processed ?? 0)} />
				<MetricCard label="Queue Depth" value={String(pipelineData.queue_depth ?? 0)} />
				<MetricCard
					label="Error Rate"
					value={formatPercent(pipelineData.error_rate ?? 0, 1, "en-US")}
				/>
			</div>
			{#if pipelineData.checked_at}
				<p class="mt-3 text-xs text-[var(--netz-text-muted)]">
					Checked at
					<time datetime={pipelineData.checked_at}>
						{formatDateTime(pipelineData.checked_at, "en-US")}
					</time>
				</p>
			{/if}
		{/if}
	</SectionCard>

	<!-- Worker Status Table -->
	<SectionCard title="Workers">
		{#if healthErrors.workers}
			<div
				class="rounded-lg border px-4 py-3 text-sm"
				style="border-color: var(--netz-warning); background-color: color-mix(in srgb, var(--netz-warning) 12%, var(--netz-surface)); color: var(--netz-text-primary);"
				role="alert"
			>
				<p class="font-medium text-[var(--netz-warning)]">Worker status unavailable</p>
				<p class="mt-1">{healthErrors.workers}</p>
			</div>
		{:else if data.workers.length > 0}
			<div class="mb-4 flex flex-wrap items-center gap-3">
				<label class="text-sm text-[var(--netz-text-secondary)]">
					<span class="mr-2 font-medium text-[var(--netz-text-primary)]">Status</span>
					<select
						bind:value={workerStatusFilter}
						class="rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] px-3 py-2 text-sm text-[var(--netz-text-primary)]"
					>
						<option value="all">All statuses</option>
						{#each workerStatusOptions as status}
							<option value={status}>{status}</option>
						{/each}
					</select>
				</label>
				<p class="text-xs text-[var(--netz-text-muted)]">
					{workerRows.length} of {data.workers.length} workers
				</p>
			</div>
			<DataTable
				data={workerRows as Record<string, unknown>[]}
				columns={workerColumns}
				pageSize={100}
				filterColumn="name"
				filterPlaceholder="Filter workers by name"
			/>
		{:else}
			<p class="text-[var(--netz-text-muted)]">No workers registered.</p>
		{/if}
	</SectionCard>

	<!-- Worker Log Feed -->
	<SectionCard title="Worker Logs">
		<WorkerLogFeed token={data.token} />
	</SectionCard>
</div>
