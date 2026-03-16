<!--
  System Health Dashboard — worker status cards, pipeline stats, tenant usage.
  Auto-refreshes every 30 seconds.
-->
<script lang="ts">
	import { PageHeader, DataCard, Badge, DataTable } from "@netz/ui";
	import type { PageData } from "./$types";
	import { invalidateAll } from "$app/navigation";
	import { onMount } from "svelte";

	let { data }: { data: PageData } = $props();

	interface WorkerStatus {
		name: string;
		last_run: string | null;
		duration_seconds: number | null;
		status: string;
		error_count: number;
	}

	interface PipelineStats {
		documents_processed: number;
		queue_depth: number;
		error_rate: number;
	}

	let workers = $derived(data.workers as WorkerStatus[]);
	let pipelines = $derived(data.pipelines as PipelineStats);

	function statusColor(status: string): string {
		switch (status) {
			case "healthy": return "bg-green-100 text-green-700";
			case "degraded": return "bg-yellow-100 text-yellow-700";
			case "error": return "bg-red-100 text-red-700";
			default: return "bg-gray-100 text-gray-500";
		}
	}

	function formatDuration(seconds: number | null): string {
		if (seconds == null) return "—";
		if (seconds < 1) return `${Math.round(seconds * 1000)}ms`;
		return `${seconds.toFixed(1)}s`;
	}

	function formatTime(iso: string | null): string {
		if (!iso) return "Never";
		return new Date(iso).toLocaleString();
	}

	// Auto-refresh every 30s
	onMount(() => {
		const interval = setInterval(() => invalidateAll(), 30_000);
		return () => clearInterval(interval);
	});

	const usageColumns = [
		{ accessorKey: "organization_id", header: "Organization" },
		{ accessorKey: "api_calls", header: "API Calls" },
		{ accessorKey: "storage_bytes", header: "Storage" },
		{ accessorKey: "memos_generated", header: "Memos" },
	];
</script>

<PageHeader title="System Health" />

<div class="space-y-8 p-6">
	<!-- Pipeline Stats -->
	<section>
		<h2 class="mb-3 text-lg font-semibold text-[var(--netz-text-primary)]">Pipeline</h2>
		<div class="grid grid-cols-1 gap-4 sm:grid-cols-3">
			<DataCard label="Documents Processed" value={String(pipelines.documents_processed)} />
			<DataCard label="Queue Depth" value={String(pipelines.queue_depth)} />
			<DataCard label="Error Rate" value={`${(pipelines.error_rate * 100).toFixed(2)}%`} />
		</div>
	</section>

	<!-- Worker Status -->
	<section>
		<h2 class="mb-3 text-lg font-semibold text-[var(--netz-text-primary)]">Workers</h2>
		<div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
			{#each workers as worker}
				<div class="rounded-lg border border-[var(--netz-border)] p-4">
					<div class="flex items-center justify-between">
						<h3 class="font-medium text-[var(--netz-text-primary)]">{worker.name}</h3>
						<span class={`rounded-full px-2 py-0.5 text-xs font-medium ${statusColor(worker.status)}`}>
							{worker.status}
						</span>
					</div>
					<div class="mt-3 space-y-1 text-xs text-[var(--netz-text-muted)]">
						<div class="flex justify-between">
							<span>Last Run</span>
							<span>{formatTime(worker.last_run)}</span>
						</div>
						<div class="flex justify-between">
							<span>Duration</span>
							<span>{formatDuration(worker.duration_seconds)}</span>
						</div>
						<div class="flex justify-between">
							<span>Errors</span>
							<span class={worker.error_count > 0 ? "text-red-600 font-medium" : ""}>{worker.error_count}</span>
						</div>
					</div>
				</div>
			{/each}
		</div>
	</section>

	<!-- Tenant Usage -->
	<section>
		<h2 class="mb-3 text-lg font-semibold text-[var(--netz-text-primary)]">Tenant Usage</h2>
		{#if (data.usage as unknown[]).length > 0}
			<DataTable data={data.usage} columns={usageColumns} />
		{:else}
			<p class="text-sm text-[var(--netz-text-muted)]">No usage data available yet.</p>
		{/if}
	</section>
</div>
