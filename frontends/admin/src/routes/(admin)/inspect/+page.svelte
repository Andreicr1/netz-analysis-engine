<!--
  Data Lake Inspection — DuckDB-powered data lake health metrics.
  Fetches 5 inspection endpoints on demand (client-side, per selected tenant + vertical).
-->
<script lang="ts">
	import { DataTable, MetricCard, PageHeader, SectionCard, Button, Select, EmptyState, Toast, ActionButton } from "@netz/ui";
	import { formatNumber, formatDateTime } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import type { PageData } from "./$types";

	type Tenant = { organization_id: string; org_name: string };

	type ChunkStats = {
		total_chunks: number;
		total_documents: number;
		total_chars: number;
		avg_chunk_chars: number;
		median_chunk_chars: number;
		p95_chunk_chars: number;
		doc_type_distribution: Record<string, number>;
		org_id: string;
		vertical: string;
		queried_at: string;
	};

	type InspectResult<T> = {
		results: T[];
		count: number;
		org_id: string;
		vertical: string;
		queried_at: string;
	};

	type DocumentCoverage = {
		document_id: string;
		title?: string;
		has_chunks: boolean;
		chunk_count: number;
		last_processed?: string | null;
	};

	type DimensionMismatch = {
		document_id: string;
		expected_dim: number;
		actual_dim: number;
		model: string;
	};

	type ExtractionQuality = {
		document_id: string;
		title?: string;
		confidence: number;
		char_count: number;
	};

	type StaleEmbedding = {
		document_id: string;
		embedding_date?: string | null;
		current_model?: string;
		embedded_model?: string;
	};

	let { data }: { data: PageData & { tenants: Tenant[] } } = $props();

	let selectedOrgId = $state("");
	let selectedVertical = $state("wealth");
	let inspecting = $state(false);
	let inspectError = $state<string | null>(null);
	let toast = $state<{ message: string; type: "success" | "error" | "warning" | "info" } | null>(null);

	// Results
	let chunkStats = $state<ChunkStats | null>(null);
	let coverage = $state<InspectResult<DocumentCoverage> | null>(null);
	let embeddingAudit = $state<InspectResult<DimensionMismatch> | null>(null);
	let extractionQuality = $state<InspectResult<ExtractionQuality> | null>(null);
	let staleEmbeddings = $state<InspectResult<StaleEmbedding> | null>(null);
	let hasResults = $derived(chunkStats !== null);

	const verticalOptions = [
		{ value: "wealth", label: "Wealth" },
		{ value: "credit", label: "Credit" },
	];

	async function runInspection() {
		if (!selectedOrgId) {
			inspectError = "Select a tenant first";
			return;
		}

		inspecting = true;
		inspectError = null;

		try {
			const api = createClientApiClient(() => Promise.resolve(data.token));
			const base = `/admin/inspect/${selectedOrgId}/${selectedVertical}`;

			const [chunkRes, covRes, embRes, extRes, staleRes] = await Promise.allSettled([
				api.get<ChunkStats>(`${base}/chunk-stats`),
				api.get<InspectResult<DocumentCoverage>>(`${base}/coverage`),
				api.get<InspectResult<DimensionMismatch>>(`${base}/embedding-audit`),
				api.get<InspectResult<ExtractionQuality>>(`${base}/extraction-quality`),
				api.get<InspectResult<StaleEmbedding>>(`${base}/stale-embeddings`),
			]);

			chunkStats = chunkRes.status === "fulfilled" ? chunkRes.value : null;
			coverage = covRes.status === "fulfilled" ? covRes.value : null;
			embeddingAudit = embRes.status === "fulfilled" ? embRes.value : null;
			extractionQuality = extRes.status === "fulfilled" ? extRes.value : null;
			staleEmbeddings = staleRes.status === "fulfilled" ? staleRes.value : null;

			const failures = [chunkRes, covRes, embRes, extRes, staleRes].filter(r => r.status === "rejected").length;
			if (failures > 0) {
				toast = { message: `${failures} of 5 inspection queries failed`, type: "warning" };
			} else {
				toast = { message: "Inspection complete", type: "success" };
			}
		} catch (e) {
			inspectError = e instanceof Error ? e.message : "Inspection failed";
		} finally {
			inspecting = false;
		}
	}

	// ── DataTable columns ──
	const coverageColumns = [
		{ accessorKey: "document_id", header: "Document ID" },
		{ accessorKey: "title", header: "Title", cell: (info: any) => String(info.getValue() ?? "—") },
		{ accessorKey: "has_chunks", header: "Has Chunks", cell: (info: any) => info.getValue() ? "Yes" : "No" },
		{ accessorKey: "chunk_count", header: "Chunks", cell: (info: any) => String(info.getValue() ?? 0) },
		{
			accessorKey: "last_processed",
			header: "Last Processed",
			cell: (info: any) => {
				const val = info.getValue();
				return val ? formatDateTime(val, "en-US") : "Never";
			},
		},
	] as any;

	const mismatchColumns = [
		{ accessorKey: "document_id", header: "Document ID" },
		{ accessorKey: "expected_dim", header: "Expected Dim" },
		{ accessorKey: "actual_dim", header: "Actual Dim" },
		{ accessorKey: "model", header: "Model" },
	] as any;

	const qualityColumns = [
		{ accessorKey: "document_id", header: "Document ID" },
		{ accessorKey: "title", header: "Title", cell: (info: any) => String(info.getValue() ?? "—") },
		{
			accessorKey: "confidence",
			header: "Confidence",
			cell: (info: any) => {
				const val = info.getValue();
				return val != null ? formatNumber(val, 2, "en-US") : "—";
			},
		},
		{
			accessorKey: "char_count",
			header: "Characters",
			cell: (info: any) => formatNumber(info.getValue() ?? 0, 0, "en-US"),
		},
	] as any;

	const staleColumns = [
		{ accessorKey: "document_id", header: "Document ID" },
		{
			accessorKey: "embedding_date",
			header: "Embedding Date",
			cell: (info: any) => {
				const val = info.getValue();
				return val ? formatDateTime(val, "en-US") : "—";
			},
		},
		{ accessorKey: "current_model", header: "Current Model", cell: (info: any) => String(info.getValue() ?? "—") },
		{ accessorKey: "embedded_model", header: "Embedded Model", cell: (info: any) => String(info.getValue() ?? "—") },
	] as any;
</script>

<div class="space-y-6 p-6">
	<PageHeader title="Data Lake Inspection" />

	<!-- Controls -->
	<div class="flex flex-wrap items-end gap-4">
		<div class="space-y-1">
			<span class="text-xs font-medium text-(--netz-text-secondary)">Tenant</span>
			<select
				bind:value={selectedOrgId}
				aria-label="Tenant"
				class="block rounded-md border border-(--netz-border) bg-(--netz-surface) px-3 py-2 text-sm text-(--netz-text-primary)"
			>
				<option value="">Select tenant...</option>
				{#each data.tenants as tenant}
					<option value={tenant.organization_id}>
						{tenant.org_name} ({tenant.organization_id.slice(0, 8)}...)
					</option>
				{/each}
			</select>
		</div>
		<div class="space-y-1">
			<span class="text-xs font-medium text-(--netz-text-secondary)">Vertical</span>
			<Select
				bind:value={selectedVertical}
				options={verticalOptions}
			/>
		</div>
		<ActionButton
			onclick={runInspection}
			loading={inspecting}
			loadingText="Inspecting..."
			disabled={!selectedOrgId}
		>
			Inspect
		</ActionButton>
	</div>

	{#if inspectError}
		<div
			class="rounded-lg border px-4 py-3 text-sm"
			style="border-color: var(--netz-danger); background-color: color-mix(in srgb, var(--netz-danger) 12%, var(--netz-surface)); color: var(--netz-text-primary);"
			role="alert"
		>
			<p class="font-medium text-(--netz-danger)">Inspection failed</p>
			<p class="mt-1">{inspectError}</p>
		</div>
	{/if}

	{#if !hasResults && !inspecting}
		<EmptyState
			title="No Inspection Data"
			description="Select a tenant and vertical, then click Inspect to view data lake metrics."
		/>
	{/if}

	{#if hasResults}
		<!-- Chunk Statistics -->
		<SectionCard title="Chunk Statistics">
			{#if chunkStats}
				<div class="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
					<MetricCard label="Total Documents" value={formatNumber(chunkStats.total_documents, 0, "en-US")} />
					<MetricCard label="Total Chunks" value={formatNumber(chunkStats.total_chunks, 0, "en-US")} />
					<MetricCard label="Total Characters" value={formatNumber(chunkStats.total_chars, 0, "en-US")} />
					<MetricCard label="Avg Chunk Size" value={formatNumber(chunkStats.avg_chunk_chars, 0, "en-US")} sublabel="chars" />
					<MetricCard label="Median Chunk" value={formatNumber(chunkStats.median_chunk_chars, 0, "en-US")} sublabel="chars" />
					<MetricCard label="P95 Chunk" value={formatNumber(chunkStats.p95_chunk_chars, 0, "en-US")} sublabel="chars" />
				</div>
				{#if chunkStats.doc_type_distribution && Object.keys(chunkStats.doc_type_distribution).length > 0}
					<div class="mt-4">
						<p class="mb-2 text-xs font-medium text-(--netz-text-secondary)">Document Type Distribution</p>
						<div class="flex flex-wrap gap-2">
							{#each Object.entries(chunkStats.doc_type_distribution) as [docType, count]}
								<span class="rounded-full bg-(--netz-surface-highlight) px-3 py-1 text-xs font-medium text-(--netz-text-primary)">
									{docType}: {count}
								</span>
							{/each}
						</div>
					</div>
				{/if}
				<p class="mt-3 text-xs text-(--netz-text-muted)">
					Queried at {formatDateTime(chunkStats.queried_at, "en-US")}
				</p>
			{:else}
				<p class="text-sm text-(--netz-text-muted)">Chunk statistics unavailable.</p>
			{/if}
		</SectionCard>

		<!-- Coverage -->
		<SectionCard title="Coverage" collapsible>
			{#if coverage}
				<div class="mb-4 grid grid-cols-2 gap-4 sm:grid-cols-3">
					<MetricCard label="Total Documents" value={String(coverage.count)} />
					<MetricCard
						label="With Chunks"
						value={String(coverage.results.filter(d => d.has_chunks).length)}
						status="ok"
					/>
					<MetricCard
						label="Missing Chunks"
						value={String(coverage.results.filter(d => !d.has_chunks).length)}
						status={coverage.results.some(d => !d.has_chunks) ? "warn" : "ok"}
					/>
				</div>
				{#if coverage.results.length > 0}
					<DataTable
						data={coverage.results as unknown as Record<string, unknown>[]}
						columns={coverageColumns}
						pageSize={20}
					/>
				{/if}
			{:else}
				<p class="text-sm text-(--netz-text-muted)">Coverage data unavailable.</p>
			{/if}
		</SectionCard>

		<!-- Embedding Audit -->
		<SectionCard title="Embedding Audit" collapsible>
			{#if embeddingAudit}
				<div class="mb-4 grid grid-cols-2 gap-4 sm:grid-cols-3">
					<MetricCard label="Total Checked" value={String(embeddingAudit.count)} />
					<MetricCard
						label="Dimension Mismatches"
						value={String(embeddingAudit.results.length)}
						status={embeddingAudit.results.length > 0 ? "breach" : "ok"}
					/>
				</div>
				{#if embeddingAudit.results.length > 0}
					<DataTable
						data={embeddingAudit.results as unknown as Record<string, unknown>[]}
						columns={mismatchColumns}
						pageSize={20}
					/>
				{:else}
					<p class="text-sm text-(--netz-text-muted)">No dimension mismatches detected.</p>
				{/if}
			{:else}
				<p class="text-sm text-(--netz-text-muted)">Embedding audit unavailable.</p>
			{/if}
		</SectionCard>

		<!-- Extraction Quality -->
		<SectionCard title="Extraction Quality" collapsible>
			{#if extractionQuality}
				<div class="mb-4 grid grid-cols-2 gap-4 sm:grid-cols-3">
					<MetricCard label="Documents Checked" value={String(extractionQuality.count)} />
					<MetricCard
						label="Low Quality"
						value={String(extractionQuality.results.length)}
						status={extractionQuality.results.length > 0 ? "warn" : "ok"}
					/>
				</div>
				{#if extractionQuality.results.length > 0}
					<DataTable
						data={extractionQuality.results as unknown as Record<string, unknown>[]}
						columns={qualityColumns}
						pageSize={20}
					/>
				{:else}
					<p class="text-sm text-(--netz-text-muted)">All extractions are within quality thresholds.</p>
				{/if}
			{:else}
				<p class="text-sm text-(--netz-text-muted)">Extraction quality data unavailable.</p>
			{/if}
		</SectionCard>

		<!-- Stale Embeddings -->
		<SectionCard title="Stale Embeddings" collapsible>
			{#if staleEmbeddings}
				<div class="mb-4 grid grid-cols-2 gap-4 sm:grid-cols-3">
					<MetricCard
						label="Stale Count"
						value={String(staleEmbeddings.results.length)}
						status={staleEmbeddings.results.length > 0 ? "warn" : "ok"}
					/>
				</div>
				{#if staleEmbeddings.results.length > 0}
					<DataTable
						data={staleEmbeddings.results as unknown as Record<string, unknown>[]}
						columns={staleColumns}
						pageSize={20}
					/>
				{:else}
					<p class="text-sm text-(--netz-text-muted)">No stale embeddings found. All embeddings use the current model.</p>
				{/if}
			{:else}
				<p class="text-sm text-(--netz-text-muted)">Stale embeddings data unavailable.</p>
			{/if}
		</SectionCard>
	{/if}
</div>

<!-- Toast notification -->
{#if toast}
	<Toast
		message={toast.message}
		type={toast.type}
		onDismiss={() => toast = null}
	/>
{/if}
