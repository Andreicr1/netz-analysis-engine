<!--
  Document detail — metadata, version history, submit for review.
-->
<script lang="ts">
	import { Card, StatusBadge, Button, EmptyState, ActionButton, formatDate } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import { resolveCreditStatus } from "$lib/utils/status-maps";
	import { invalidateAll } from "$app/navigation";
	import { getContext } from "svelte";
	import type { PageData } from "./$types";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	let doc = $derived(data.document as Record<string, unknown>);
	let versions = $derived((data.versions ?? []) as Array<Record<string, unknown>>);
	let submitting = $state(false);
	let error = $state<string | null>(null);

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

<div class="p-6">
	<div class="mb-4 flex items-center justify-between">
		<div>
			<h2 class="text-xl font-semibold text-[var(--netz-text-primary)]">
				{doc.title ?? "Document"}
			</h2>
			<div class="mt-1 flex items-center gap-2">
				<StatusBadge status={String(doc.status ?? "")} type="default" resolve={resolveCreditStatus} />
				<span class="text-sm text-[var(--netz-text-muted)]">{doc.classification ?? doc.domain ?? ""}</span>
			</div>
		</div>
		<ActionButton onclick={submitForReview} loading={submitting} loadingText="Submitting...">
			Submit for Review
		</ActionButton>
	</div>

	{#if error}
		<div class="mb-4 rounded-md border border-[var(--netz-status-error)] p-3 text-sm text-[var(--netz-status-error)]">
			{error}
		</div>
	{/if}

	<!-- Metadata -->
	<Card class="mb-6 p-6">
		<h3 class="mb-4 text-lg font-semibold">Document Metadata</h3>
		<div class="grid gap-4 md:grid-cols-2">
			{#each Object.entries(doc).filter(([k]) => !["id", "organization_id", "content", "embedding"].includes(k)) as [key, value]}
				<div>
					<p class="text-xs text-[var(--netz-text-muted)]">{key}</p>
					<p class="text-sm font-medium text-[var(--netz-text-primary)]">{String(value ?? "—")}</p>
				</div>
			{/each}
		</div>
	</Card>

	<!-- Version History -->
	<Card class="p-6">
		<h3 class="mb-4 text-lg font-semibold">Version History</h3>
		{#if versions.length === 0}
			<EmptyState title="No versions" description="Version history will appear here." />
		{:else}
			<div class="space-y-2">
				{#each versions as version}
					<div class="flex items-center justify-between rounded-md border border-[var(--netz-border)] p-3">
						<div>
							<p class="text-sm font-medium text-[var(--netz-text-primary)]">
								Version {version.version ?? version.version_number ?? ""}
							</p>
							<p class="text-xs text-[var(--netz-text-muted)]">
								{version.created_at ? formatDate(String(version.created_at)) : ""}
							</p>
						</div>
						<StatusBadge status={String(version.status ?? "")} type="default" resolve={resolveCreditStatus} />
					</div>
				{/each}
			</div>
		{/if}
	</Card>
</div>
