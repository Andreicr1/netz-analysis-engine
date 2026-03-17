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

	const MAX_FILE_SIZE = 50 * 1024 * 1024; // 50MB

	let file = $state<File | null>(null);
	let uploading = $state(false);
	let jobId = $state<string | null>(null);
	let uploadError = $state<string | null>(null);

	/**
	 * Validate magic bytes to verify file content matches expected document types.
	 * Returns true if the file header matches a known document signature,
	 * or if the file is a text format (csv/txt) with no magic bytes.
	 */
	async function validateMagicBytes(f: File): Promise<boolean> {
		const ext = f.name.split(".").pop()?.toLowerCase();
		// Text formats have no magic bytes — skip validation
		if (ext === "csv" || ext === "txt") return true;

		const header = new Uint8Array(await f.slice(0, 4).arrayBuffer());
		const validSignatures = [
			[0x25, 0x50, 0x44, 0x46], // %PDF
			[0x50, 0x4b, 0x03, 0x04], // PK (ZIP-based Office: .docx, .xlsx)
			[0xd0, 0xcf, 0x11, 0xe0], // OLE compound (legacy .doc, .xls)
		];
		return validSignatures.some((sig) => sig.every((b, i) => header[i] === b));
	}

	/** Validate file size and magic bytes. Sets uploadError and returns false on failure. */
	async function validateFile(f: File): Promise<boolean> {
		if (f.size > MAX_FILE_SIZE) {
			uploadError = `File "${f.name}" exceeds 50 MB limit (${(f.size / 1024 / 1024).toFixed(1)} MB)`;
			return false;
		}
		if (!(await validateMagicBytes(f))) {
			uploadError = `File "${f.name}" does not appear to be a valid document (unrecognised file header)`;
			return false;
		}
		uploadError = null;
		return true;
	}

	async function handleDrop(event: DragEvent) {
		event.preventDefault();
		const files = event.dataTransfer?.files;
		if (files && files.length > 0) {
			const candidate = files[0] ?? null;
			if (candidate && (await validateFile(candidate))) {
				file = candidate;
			} else {
				file = null;
			}
		}
	}

	async function handleFileSelect(event: Event) {
		const input = event.target as HTMLInputElement;
		if (input.files && input.files.length > 0) {
			const candidate = input.files[0] ?? null;
			if (candidate && (await validateFile(candidate))) {
				file = candidate;
			} else {
				file = null;
			}
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
				class="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-[var(--netz-border)] p-12 transition-colors hover:border-[var(--netz-brand-primary)]"
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
