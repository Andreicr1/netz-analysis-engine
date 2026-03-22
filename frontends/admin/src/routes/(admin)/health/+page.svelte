<!--
  Health Dashboard — System health monitoring with live worker logs.
  Auto-refresh via client-side $effect (NOT invalidateAll).
  Worker trigger buttons call wealth backend endpoints.
-->
<script lang="ts">
	import { DataTable, MetricCard, PageHeader, SectionCard, Button, Input, Select, ConfirmDialog, Toast, formatDateTime, formatNumber, formatPercent } from "@netz/ui";
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
		checked_at?: string | null;
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
	// svelte-ignore state_referenced_locally
	let healthData = $state(data.services);
	// svelte-ignore state_referenced_locally
	let pipelineData = $state(data.pipelines);
	// svelte-ignore state_referenced_locally
	let workerData = $state(data.workers);
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
	let workerStatusOptions = $derived(Array.from(new Set(workerData.map((worker) => worker.status))).sort());
	let workerRows = $derived(
		workerStatusFilter === "all"
			? workerData
			: workerData.filter((worker) => worker.status === workerStatusFilter),
	);

	// ── Worker triggers ──
	type WorkerTrigger = {
		name: string;
		label: string;
		endpoint: string;
		scope: "wealth" | "global";
		hasParams?: boolean;
	};

	const WORKER_TRIGGERS: WorkerTrigger[] = [
		{ name: "ingestion", label: "NAV Ingestion (legacy)", endpoint: "/workers/run-ingestion", scope: "wealth" },
		{ name: "instrument_ingestion", label: "Instrument NAV Ingestion", endpoint: "/workers/run-instrument-ingestion", scope: "wealth", hasParams: true },
		{ name: "macro_ingestion", label: "Macro Data (FRED)", endpoint: "/workers/run-macro-ingestion", scope: "global" },
		{ name: "benchmark_ingest", label: "Benchmark NAV", endpoint: "/workers/run-benchmark-ingest", scope: "global" },
		{ name: "risk_calc", label: "Risk Calculation", endpoint: "/workers/run-risk-calc", scope: "wealth" },
		{ name: "portfolio_eval", label: "Portfolio Evaluation", endpoint: "/workers/run-portfolio-eval", scope: "wealth" },
		{ name: "screening_batch", label: "Screening Batch", endpoint: "/workers/run-screening-batch", scope: "wealth" },
		{ name: "watchlist_check", label: "Watchlist Check", endpoint: "/workers/run-watchlist-check", scope: "wealth" },
		{ name: "fact_sheet_gen", label: "Fact Sheet Generation", endpoint: "/workers/run-fact-sheet-gen", scope: "global" },
	];

	let triggeringWorker = $state<string | null>(null);
	let confirmTrigger = $state<WorkerTrigger | null>(null);
	let showConfirmTrigger = $state(false);
	let lookbackDays = $state(30);
	let toast = $state<{ message: string; type: "success" | "error" | "warning" | "info" } | null>(null);

	function findTrigger(workerName: string): WorkerTrigger | undefined {
		return WORKER_TRIGGERS.find(w => w.name === workerName);
	}

	async function triggerWorker(workerName: string) {
		const trigger = findTrigger(workerName);
		if (!trigger) return;

		triggeringWorker = workerName;
		try {
			const api = createClientApiClient(() => Promise.resolve(data.token));
			let endpoint = trigger.endpoint;
			if (trigger.name === "instrument_ingestion") {
				endpoint += `?lookback_days=${lookbackDays}`;
			}
			await api.post(endpoint, {});
			toast = { message: `${trigger.label} scheduled`, type: "success" };
			// Refresh worker status after delay for backend to register the job
			setTimeout(async () => {
				try {
					const refreshApi = createClientApiClient(() => Promise.resolve(data.token));
					workerData = await refreshApi.get("/admin/health/workers");
				} catch { /* silent */ }
				triggeringWorker = null;
			}, 2000);
		} catch (e) {
			toast = { message: `Failed to trigger ${trigger.label}: ${e instanceof Error ? e.message : "Unknown error"}`, type: "error" };
			triggeringWorker = null;
		}
	}

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
			accessorKey: "checked_at",
			header: "Checked At",
			cell: (info: any) => {
				const worker = info.row.original as HealthWorker;
				return worker.checked_at ? formatDateTime(worker.checked_at, "en-US") : "—";
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
				workerData = await api.get("/admin/health/workers");
			} catch {
				/* silent refresh failure */
			}
		}, 30_000);
		return () => clearInterval(interval);
	});
</script>

<div class="space-y-(--netz-space-section-gap) p-(--netz-space-page-gutter)">
	<PageHeader title="System Health" />

	{#if degradedMessage}
		<div
			class="rounded-xl border px-4 py-3 text-sm"
			style="border-color: var(--netz-warning); background-color: color-mix(in srgb, var(--netz-warning) 12%, var(--netz-surface)); color: var(--netz-text-primary);"
			role="alert"
		>
			<p class="font-medium text-(--netz-warning)">Degraded state</p>
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
				<p class="font-medium text-(--netz-warning)">Service health unavailable</p>
				<p class="mt-1">{healthErrors.services}</p>
			</div>
		{:else if healthData.length > 0}
			<div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
				{#each healthData as service}
					<ServiceHealthCard {service} />
				{/each}
			</div>
		{:else}
			<div class="rounded-lg border border-dashed border-(--netz-border) px-4 py-3 text-sm text-(--netz-text-muted)">
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
				<p class="font-medium text-(--netz-warning)">Pipeline stats unavailable</p>
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
				<p class="mt-3 text-xs text-(--netz-text-muted)">
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
				<p class="font-medium text-(--netz-warning)">Worker status unavailable</p>
				<p class="mt-1">{healthErrors.workers}</p>
			</div>
		{:else if workerData.length > 0}
			<div class="mb-4 flex flex-wrap items-center gap-3">
				<div class="flex items-center gap-2 text-sm text-(--netz-text-secondary)">
					<span class="font-medium text-(--netz-text-primary)">Status</span>
					<Select
						bind:value={workerStatusFilter}
						options={[{ value: "all", label: "All statuses" }, ...workerStatusOptions.map((s) => ({ value: s, label: s }))]}
						class="w-44"
					/>
				</div>
				<p class="text-xs text-(--netz-text-muted)">
					{workerRows.length} of {workerData.length} workers
				</p>
			</div>
			<DataTable
				data={workerRows as Record<string, unknown>[]}
				columns={workerColumns}
				pageSize={100}
				filterColumn="name"
				filterPlaceholder="Filter workers by name"
			>
				{#snippet expandedRow(row)}
					{@const worker = row as HealthWorker}
					{@const trigger = findTrigger(worker.name)}
					<div class="grid grid-cols-2 gap-4 px-4 py-3 text-sm sm:grid-cols-3">
						<div>
							<p class="text-xs text-(--netz-text-muted)">Worker</p>
							<p class="font-mono font-medium text-(--netz-text-primary)">{worker.name}</p>
						</div>
						<div>
							<p class="text-xs text-(--netz-text-muted)">Status</p>
							<p class="text-(--netz-text-primary)">{worker.status}</p>
						</div>
						<div>
							<p class="text-xs text-(--netz-text-muted)">Error Count</p>
							<p class="{worker.error_count > 0 ? "text-(--netz-danger)" : "text-(--netz-text-primary)"}">{worker.error_count}</p>
						</div>
						<div>
							<p class="text-xs text-(--netz-text-muted)">Last Run</p>
							<p class="text-(--netz-text-primary)">{worker.last_run ? formatDateTime(worker.last_run, "en-US") : "Never"}</p>
						</div>
						<div>
							<p class="text-xs text-(--netz-text-muted)">Checked At</p>
							<p class="text-(--netz-text-primary)">{worker.checked_at ? formatDateTime(worker.checked_at, "en-US") : "—"}</p>
						</div>
						<div>
							<p class="text-xs text-(--netz-text-muted)">Duration</p>
							<p class="text-(--netz-text-primary)">{worker.duration_ms !== null ? `${formatNumber(worker.duration_ms, 0, "en-US")}ms` : "—"}</p>
						</div>
						{#if worker.error_count > 0}
							<div class="col-span-2 sm:col-span-3">
								<p class="text-xs text-(--netz-text-muted)">Note</p>
								<p class="text-xs text-(--netz-warning)">This worker has recorded errors. Check the log feed below for details.</p>
							</div>
						{/if}
						{#if trigger}
							<div class="col-span-2 flex items-center gap-3 border-t border-(--netz-border) pt-3 sm:col-span-3">
								{#if trigger.name === "instrument_ingestion"}
									<label class="flex items-center gap-2 text-xs text-(--netz-text-secondary)">
										Lookback days
										<input
											type="number"
											min="1"
											max="1095"
											bind:value={lookbackDays}
											class="w-20 rounded-md border border-(--netz-border) bg-(--netz-surface) px-2 py-1 text-sm text-(--netz-text-primary)"
										/>
									</label>
								{/if}
								<Button
									size="sm"
									variant="outline"
									disabled={worker.status === "running" || triggeringWorker === worker.name}
									onclick={() => { confirmTrigger = trigger; showConfirmTrigger = true; }}
								>
									{triggeringWorker === worker.name ? "Starting..." : "Run Now"}
								</Button>
							</div>
						{/if}
					</div>
				{/snippet}
			</DataTable>
		{:else}
			<p class="text-(--netz-text-muted)">No workers registered.</p>
		{/if}
	</SectionCard>

	<!-- Worker Log Feed -->
	<SectionCard title="Worker Logs">
		<WorkerLogFeed token={data.token} />
	</SectionCard>
</div>

<!-- Worker Trigger Confirmation -->
<ConfirmDialog
	bind:open={showConfirmTrigger}
	title="Run Worker"
	message={confirmTrigger ? `Trigger "${confirmTrigger.label}"? This may take several minutes.` : ""}
	confirmLabel="Run"
	confirmVariant="default"
	onConfirm={() => { if (confirmTrigger) { triggerWorker(confirmTrigger.name); } showConfirmTrigger = false; confirmTrigger = null; }}
	onCancel={() => { showConfirmTrigger = false; confirmTrigger = null; }}
/>

<!-- Toast notification -->
{#if toast}
	<Toast
		message={toast.message}
		type={toast.type}
		onDismiss={() => toast = null}
	/>
{/if}
