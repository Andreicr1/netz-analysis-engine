<!--
  Document detail — metadata, AI classification provenance, version history, event timeline.
-->
<script lang="ts">
	import {
		Card,
		StatusBadge,
		Button,
		EmptyState,
		ActionButton,
		AuditTrailPanel,
		PageHeader,
		SectionCard,
		formatDate,
		formatPercent,
	} from "@netz/ui";
	import type { AuditTrailEntry } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import { resolveCreditStatus } from "$lib/utils/status-maps";
	import { invalidateAll } from "$app/navigation";
	import { getContext } from "svelte";
	import type { PageData } from "./$types";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	let doc = $derived(data.document as Record<string, unknown>);
	let versions = $derived((data.versions ?? []) as Array<Record<string, unknown>>);
	let timelineRaw = $derived((data.timeline ?? []) as Array<Record<string, unknown>>);
	let submitting = $state(false);
	let error = $state<string | null>(null);

	// ── AI Classification provenance ─────────────────────────
	const classificationLayerLabel = $derived.by(() => {
		const layer = doc.classification_layer as number | null | undefined;
		if (layer === 1) return "Rules";
		if (layer === 2) return "Embeddings";
		if (layer === 3) return "LLM";
		return "—";
	});

	const classificationModel = $derived(
		(doc.classification_model as string | null | undefined) ?? "—",
	);

	const classificationConfidence = $derived.by(() => {
		const confidence = doc.classification_confidence as number | null | undefined;
		if (confidence == null) return "—";
		return formatPercent(confidence);
	});

	// ── Document event timeline → AuditTrailEntry[] ──────────
	const timelineEntries = $derived.by<AuditTrailEntry[]>(() => {
		return timelineRaw.map((event) => ({
			id: String(event.id ?? ""),
			actor: String(event.actor ?? event.actor_email ?? "System"),
			actorEmail: event.actor_email ? String(event.actor_email) : undefined,
			actorCapacity: event.actor_capacity ? String(event.actor_capacity) : undefined,
			timestamp: String(event.timestamp ?? event.created_at ?? new Date().toISOString()),
			action: String(event.action ?? event.event_type ?? "Event"),
			scope: String(event.scope ?? event.document_title ?? doc.title ?? "Document"),
			rationale: event.rationale ? String(event.rationale) : undefined,
			outcome: String(event.outcome ?? event.status ?? "recorded"),
			status: (event.status_severity as AuditTrailEntry["status"]) ?? "info",
			immutable: true,
			sourceSystem: event.source_system ? String(event.source_system) : "document-pipeline",
		}));
	});

	async function submitForReview() {
		submitting = true;
		error = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/funds/${data.fundId}/document-reviews`, { document_id: data.documentId });
			await invalidateAll();
		} catch (e) {
			error = e instanceof Error ? e.message : "Failed to submit for review";
		} finally {
			submitting = false;
		}
	}
</script>

<div class="px-6">
	<PageHeader
		title={String(doc.title ?? "Document")}
		breadcrumbs={[
			{ label: "Funds", href: "/funds" },
			{ label: "Documents", href: `/funds/${data.fundId}/documents` },
			{ label: String(doc.title ?? "Document") },
		]}
	>
		{#snippet actions()}
			<ActionButton onclick={submitForReview} loading={submitting} loadingText="Submitting...">
				Submit for Review
			</ActionButton>
		{/snippet}
	</PageHeader>

	<div class="mb-4 flex items-center gap-2">
		<StatusBadge status={String(doc.status ?? "")} type="default" resolve={resolveCreditStatus} />
		<span class="text-sm text-(--netz-text-muted)">{doc.classification ?? doc.domain ?? ""}</span>
	</div>

	{#if error}
		<div
			role="alert"
			class="mb-4 rounded-md border border-(--netz-status-error) p-3 text-sm text-(--netz-status-error)"
		>
			{error}
		</div>
	{/if}

	<div class="space-y-6">
		<!-- AI Classification provenance -->
		<SectionCard title="AI Classification" subtitle="Hybrid classifier provenance">
			<div class="grid gap-4 sm:grid-cols-3">
				<div>
					<p class="text-xs font-medium uppercase tracking-[0.14em] text-(--netz-text-secondary)">
						Layer
					</p>
					<p class="mt-1 text-sm font-medium text-(--netz-text-primary)">
						{classificationLayerLabel}
					</p>
				</div>
				<div>
					<p class="text-xs font-medium uppercase tracking-[0.14em] text-(--netz-text-secondary)">
						Model
					</p>
					<p class="mt-1 text-sm font-medium text-(--netz-text-primary)">
						{classificationModel}
					</p>
				</div>
				<div>
					<p class="text-xs font-medium uppercase tracking-[0.14em] text-(--netz-text-secondary)">
						Confidence
					</p>
					<p class="mt-1 text-sm font-medium text-(--netz-text-primary)">
						{classificationConfidence}
					</p>
				</div>
			</div>
		</SectionCard>

		<!-- Document Metadata -->
		<SectionCard title="Document Metadata">
			<div class="grid gap-4 md:grid-cols-2">
				{#each Object.entries(doc).filter(([k]) => !["id", "organization_id", "content", "embedding", "classification_layer", "classification_model", "classification_confidence", "classification_layer_label"].includes(k)) as [key, value]}
					<div>
						<p class="text-xs text-(--netz-text-muted)">{key}</p>
						<p class="text-sm font-medium text-(--netz-text-primary)">{String(value ?? "—")}</p>
					</div>
				{/each}
			</div>
		</SectionCard>

		<!-- Version History -->
		<SectionCard title="Version History">
			{#if versions.length === 0}
				<EmptyState title="No versions" description="Version history will appear here." />
			{:else}
				<div class="space-y-2">
					{#each versions as version}
						<div class="flex items-center justify-between rounded-md border border-(--netz-border) p-3">
							<div>
								<p class="text-sm font-medium text-(--netz-text-primary)">
									Version {version.version ?? version.version_number ?? ""}
								</p>
								<p class="text-xs text-(--netz-text-muted)">
									{version.created_at ? formatDate(String(version.created_at)) : ""}
								</p>
							</div>
							<StatusBadge status={String(version.status ?? "")} type="default" resolve={resolveCreditStatus} />
						</div>
					{/each}
				</div>
			{/if}
		</SectionCard>

		<!-- Document Event Timeline -->
		<AuditTrailPanel
			entries={timelineEntries}
			title="Document Timeline"
			description="Immutable record of upload, classification, review, and decision events."
			emptyMessage="No timeline events recorded yet."
		/>
	</div>
</div>
