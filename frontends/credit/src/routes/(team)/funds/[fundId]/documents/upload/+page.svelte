<!--
  Document upload flow:
  1. Select file (drag & drop + file picker)
  2. POST /documents/upload-url → get SAS URL
  3. Upload directly to storage via SAS URL
  4. POST /documents/upload-complete → get job_id
  5. SSE stream showing pipeline stages
-->
<script lang="ts">
	import { Card, Button, EmptyState } from "@netz/ui";
	import { createSSEStream } from "@netz/ui/utils";
	import IngestionProgress from "$lib/components/IngestionProgress.svelte";
	import { createClientApiClient } from "$lib/api/client";
	import { getContext } from "svelte";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let file = $state<File | null>(null);
	let uploading = $state(false);
	let jobId = $state<string | null>(null);
	let uploadError = $state<string | null>(null);

	function handleDrop(event: DragEvent) {
		event.preventDefault();
		const files = event.dataTransfer?.files;
		if (files && files.length > 0) {
			file = files[0] ?? null;
		}
	}

	function handleFileSelect(event: Event) {
		const input = event.target as HTMLInputElement;
		if (input.files && input.files.length > 0) {
			file = input.files[0] ?? null;
		}
	}

	async function startUpload() {
		if (!file) return;
		uploading = true;
		uploadError = null;

		try {
			const api = createClientApiClient(getToken);

			// Step 1: Get SAS upload URL
			const uploadUrl = await api.post<{ upload_url: string; document_id: string }>(
				"/documents/upload-url",
				{ filename: file.name, content_type: file.type, size: file.size },
			);

			// Step 2: Upload directly to storage
			await fetch(uploadUrl.upload_url, {
				method: "PUT",
				headers: { "x-ms-blob-type": "BlockBlob", "Content-Type": file.type },
				body: file,
			});

			// Step 3: Mark complete → get job_id for SSE
			const result = await api.post<{ job_id: string }>(
				"/documents/upload-complete",
				{ document_id: uploadUrl.document_id },
			);

			jobId = result.job_id;
		} catch (err) {
			uploadError = err instanceof Error ? err.message : "Upload failed";
		} finally {
			uploading = false;
		}
	}
</script>

<div class="p-6">
	<h2 class="mb-4 text-xl font-semibold text-[var(--netz-text-primary)]">Upload Document</h2>

	{#if jobId}
		<IngestionProgress {jobId} />
	{:else}
		<Card class="p-8">
			<!-- svelte-ignore a11y_no_static_element_interactions -->
			<div
				class="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-[var(--netz-border)] p-12 transition-colors hover:border-[var(--netz-primary)]"
				ondrop={handleDrop}
				ondragover={(e) => e.preventDefault()}
			>
				{#if file}
					<p class="text-sm font-medium text-[var(--netz-text-primary)]">{file.name}</p>
					<p class="text-xs text-[var(--netz-text-muted)]">
						{(file.size / 1024 / 1024).toFixed(2)} MB
					</p>
				{:else}
					<p class="mb-2 text-sm text-[var(--netz-text-secondary)]">
						Drag & drop a file here, or click to browse
					</p>
				{/if}

				<input
					type="file"
					class="mt-3"
					accept=".pdf,.doc,.docx,.xls,.xlsx,.csv,.txt"
					onchange={handleFileSelect}
				/>
			</div>

			{#if uploadError}
				<p class="mt-3 text-sm text-[var(--netz-danger)]">{uploadError}</p>
			{/if}

			<div class="mt-4 flex justify-end">
				<Button onclick={startUpload} disabled={!file || uploading}>
					{uploading ? "Uploading..." : "Upload & Process"}
				</Button>
			</div>
		</Card>
	{/if}
</div>
