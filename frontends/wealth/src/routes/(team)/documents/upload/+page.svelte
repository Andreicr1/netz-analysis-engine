<!--
  Wealth Document Upload — two-step flow:
  1. POST /wealth/documents/upload-url → get presigned URL
  2. PUT to presigned URL (direct storage upload)
  3. POST /wealth/documents/upload-complete → get job_id
  4. Show IngestionProgress SSE stream
-->
<script lang="ts">
	import { Card, Button, PageHeader, Select, formatNumber } from "@netz/ui";
	import { FormField } from "@netz/ui";
	import IngestionProgress from "$lib/components/IngestionProgress.svelte";
	import { createClientApiClient } from "$lib/api/client";
	import { getContext } from "svelte";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	const MAX_FILE_SIZE = 100 * 1024 * 1024; // 100MB

	let file = $state<File | null>(null);
	let uploading = $state(false);
	let jobId = $state<string | null>(null);
	let uploadError = $state<string | null>(null);
	let domain = $state("other");

	async function validateMagicBytes(f: File): Promise<boolean> {
		const ext = f.name.split(".").pop()?.toLowerCase();
		if (ext === "csv" || ext === "txt") return true;

		const header = new Uint8Array(await f.slice(0, 4).arrayBuffer());
		const validSignatures = [
			[0x25, 0x50, 0x44, 0x46], // %PDF
			[0x50, 0x4b, 0x03, 0x04], // PK (ZIP-based Office)
			[0xd0, 0xcf, 0x11, 0xe0], // OLE compound (legacy Office)
		];
		return validSignatures.some((sig) => sig.every((b, i) => header[i] === b));
	}

	async function validateFile(f: File): Promise<boolean> {
		if (f.size > MAX_FILE_SIZE) {
			uploadError = `File "${f.name}" exceeds 100 MB limit (${formatNumber(f.size / 1024 / 1024, 1)} MB)`;
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

			// Step 1: Get presigned upload URL
			const uploadUrl = await api.post<{ upload_url: string; upload_id: string; blob_path: string }>(
				"/wealth/documents/upload-url",
				{
					filename: file.name,
					content_type: file.type || "application/pdf",
					domain,
				},
			);

			// Step 2: Upload directly to storage via presigned URL
			const putHeaders: Record<string, string> = {
				"Content-Type": file.type || "application/pdf",
			};
			// StorageClient uses LocalStorage — PUT to presigned URL
			await fetch(uploadUrl.upload_url, {
				method: "PUT",
				headers: putHeaders,
				body: file,
			});

			// Step 3: Mark complete → get job_id for SSE
			const result = await api.post<{ job_id: string; version_id: string; document_id: string }>(
				"/wealth/documents/upload-complete",
				{ upload_id: uploadUrl.upload_id },
			);

			jobId = result.job_id;
		} catch (err) {
			uploadError = err instanceof Error ? err.message : "Upload failed";
		} finally {
			uploading = false;
		}
	}
</script>

<div class="space-y-(--netz-space-section-gap) p-(--netz-space-page-gutter)">
	<PageHeader
		title="Upload Document"
		breadcrumbs={[{ label: "Documents", href: "/documents" }, { label: "Upload" }]}
	/>

	{#if jobId}
		<IngestionProgress {jobId} />
	{:else}
		<Card class="p-8">
			<!-- svelte-ignore a11y_no_static_element_interactions -->
			<div
				class="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-(--netz-border) p-12 transition-colors hover:border-(--netz-brand-primary)"
				ondrop={handleDrop}
				ondragover={(e) => e.preventDefault()}
			>
				{#if file}
					<p class="text-sm font-medium text-(--netz-text-primary)">{file.name}</p>
					<p class="text-xs text-(--netz-text-muted)">
						{formatNumber(file.size / 1024 / 1024, 2)} MB
					</p>
				{:else}
					<p class="mb-2 text-sm text-(--netz-text-secondary)">
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

			<div class="mt-4 max-w-xs">
				<FormField label="Document Domain">
					<Select
						bind:value={domain}
						options={[
							{ value: "dd_report", label: "DD Report" },
							{ value: "fact_sheet", label: "Fact Sheet" },
							{ value: "compliance", label: "Compliance" },
							{ value: "other", label: "Other" },
						]}
					/>
				</FormField>
			</div>

			{#if uploadError}
				<p class="mt-3 text-sm text-(--netz-status-error)">{uploadError}</p>
			{/if}

			<div class="mt-4 flex justify-end">
				<Button onclick={startUpload} disabled={!file || uploading}>
					{uploading ? "Uploading..." : "Upload & Process"}
				</Button>
			</div>
		</Card>
	{/if}
</div>
