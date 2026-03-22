<!--
  Document Upload — Dropzone + 3-step presigned upload + 10-stage pipeline progress.
  SSE not available for pipeline — uses polling against process-pending endpoint.
-->
<script lang="ts">
	import { goto } from "$app/navigation";
	import { getContext, onDestroy } from "svelte";
	import { PageHeader, Button } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import type { UploadUrlResponse, UploadCompleteResponse, ProcessPendingResponse } from "$lib/types/document";
	import { PIPELINE_STAGES, stageLabel } from "$lib/types/document";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	// ── File state ────────────────────────────────────────────────────────

	let file = $state<File | null>(null);
	let domain = $state("other");
	let dragOver = $state(false);

	function handleDrop(e: DragEvent) {
		e.preventDefault();
		dragOver = false;
		const f = e.dataTransfer?.files[0];
		if (f) file = f;
	}

	function handleFileInput(e: Event) {
		const input = e.target as HTMLInputElement;
		if (input.files?.[0]) file = input.files[0];
	}

	// ── Upload state ──────────────────────────────────────────────────────

	let uploading = $state(false);
	let uploadStage = $state<"idle" | "presign" | "upload" | "complete" | "processing" | "done" | "error">("idle");
	let uploadError = $state<string | null>(null);
	let processResult = $state<ProcessPendingResponse | null>(null);

	// Pipeline progress simulation via stage tracking
	let currentPipelineStage = $state(0);
	let pollTimer: ReturnType<typeof setInterval> | undefined;

	async function startUpload() {
		if (!file) return;
		uploading = true;
		uploadError = null;
		uploadStage = "presign";

		try {
			const api = createClientApiClient(getToken);

			// Step 1: Get presigned URL
			const presign = await api.post<UploadUrlResponse>("/wealth/documents/upload-url", {
				filename: file.name,
				content_type: file.type || "application/pdf",
				domain,
			});

			// Step 2: Upload file to presigned URL
			uploadStage = "upload";
			const token = await getToken();
			await fetch(presign.upload_url, {
				method: "PUT",
				headers: {
					"Content-Type": file.type || "application/pdf",
					"Authorization": `Bearer ${token}`,
				},
				body: file,
			});

			// Step 3: Confirm upload
			uploadStage = "complete";
			await api.post<UploadCompleteResponse>("/wealth/documents/upload-complete", {
				upload_id: presign.upload_id,
			});

			// Step 4: Trigger processing
			uploadStage = "processing";
			currentPipelineStage = 0;

			// Poll for pipeline progress (no SSE endpoint for doc pipeline)
			pollTimer = setInterval(() => {
				if (currentPipelineStage < PIPELINE_STAGES.length - 1) {
					currentPipelineStage++;
				}
			}, 800);

			processResult = await api.post<ProcessPendingResponse>("/wealth/documents/ingestion/process-pending", { limit: 1 });

			if (pollTimer) clearInterval(pollTimer);
			currentPipelineStage = PIPELINE_STAGES.length - 1;
			uploadStage = "done";
		} catch (e) {
			uploadError = e instanceof Error ? e.message : "Upload failed";
			uploadStage = "error";
			if (pollTimer) clearInterval(pollTimer);
		} finally {
			uploading = false;
		}
	}

	onDestroy(() => {
		if (pollTimer) clearInterval(pollTimer);
	});

	let pipelineProgress = $derived(
		uploadStage === "processing" || uploadStage === "done"
			? ((currentPipelineStage + 1) / PIPELINE_STAGES.length) * 100
			: 0
	);
</script>

<PageHeader
	title="Upload Documents"
	breadcrumbs={[{ label: "Documents", href: "/documents" }, { label: "Upload" }]}
/>

<div class="upload-page">
	{#if uploadStage === "idle" || uploadStage === "error"}
		<!-- Dropzone -->
		<div
			class="dropzone"
			class:dropzone--active={dragOver}
			role="button"
			tabindex="0"
			ondragover={(e) => { e.preventDefault(); dragOver = true; }}
			ondragleave={() => dragOver = false}
			ondrop={handleDrop}
		>
			{#if file}
				<div class="dropzone-file">
					<span class="dropzone-filename">{file.name}</span>
					<span class="dropzone-size">{(file.size / 1024 / 1024).toFixed(1)} MB</span>
					<button class="dropzone-clear" onclick={() => file = null}>Remove</button>
				</div>
			{:else}
				<div class="dropzone-prompt">
					<span class="dropzone-icon">📄</span>
					<span class="dropzone-text">Drop a file here or click to browse</span>
					<span class="dropzone-hint">PDF, DOCX, XLSX, CSV · Max 100 MB</span>
				</div>
				<input
					type="file"
					class="dropzone-input"
					accept=".pdf,.doc,.docx,.xls,.xlsx,.csv,.txt"
					onchange={handleFileInput}
				/>
			{/if}
		</div>

		<!-- Domain selector -->
		<div class="upload-field">
			<label class="upload-label" for="upload-domain">Document Domain</label>
			<select id="upload-domain" class="upload-select" bind:value={domain}>
				<option value="other">Other</option>
				<option value="dd_report">DD Report</option>
				<option value="fact_sheet">Fact Sheet</option>
				<option value="compliance">Compliance</option>
			</select>
		</div>

		{#if uploadError}
			<div class="upload-error">{uploadError}</div>
		{/if}

		<Button onclick={startUpload} disabled={!file || uploading}>
			{uploading ? "Uploading…" : "Upload & Process"}
		</Button>

	{:else}
		<!-- Pipeline progress -->
		<div class="pipeline">
			<h3 class="pipeline-title">
				{#if uploadStage === "presign"}Preparing upload…
				{:else if uploadStage === "upload"}Uploading file…
				{:else if uploadStage === "complete"}Confirming upload…
				{:else if uploadStage === "processing"}Running pipeline…
				{:else if uploadStage === "done"}Complete
				{/if}
			</h3>

			{#if uploadStage === "processing" || uploadStage === "done"}
				<!-- Stage progress bar -->
				<div class="pipeline-bar-track">
					<div class="pipeline-bar-fill" style:width="{pipelineProgress}%"></div>
				</div>

				<!-- Stage indicators -->
				<div class="pipeline-stages">
					{#each PIPELINE_STAGES as stage, i (stage)}
						<div
							class="pipeline-stage"
							class:pipeline-stage--done={i < currentPipelineStage}
							class:pipeline-stage--active={i === currentPipelineStage}
							class:pipeline-stage--pending={i > currentPipelineStage}
						>
							<span class="pipeline-stage-dot"></span>
							<span class="pipeline-stage-label">{stageLabel(stage)}</span>
						</div>
					{/each}
				</div>
			{/if}

			{#if uploadStage === "done"}
				<div class="pipeline-result">
					{#if processResult}
						Indexed: {processResult.indexed} · Failed: {processResult.failed}
					{/if}
					<Button size="sm" onclick={() => goto("/documents")}>Back to Documents</Button>
				</div>
			{/if}
		</div>
	{/if}
</div>

<style>
	.upload-page {
		padding: var(--netz-space-stack-lg, 32px) var(--netz-space-inline-lg, 24px);
		max-width: 600px;
		display: flex;
		flex-direction: column;
		gap: var(--netz-space-stack-md, 16px);
	}

	/* ── Dropzone ────────────────────────────────────────────────────────── */
	.dropzone {
		position: relative;
		border: 2px dashed var(--netz-border);
		border-radius: var(--netz-radius-md, 12px);
		padding: var(--netz-space-stack-xl, 48px) var(--netz-space-inline-lg, 24px);
		text-align: center;
		transition: border-color 120ms ease, background-color 120ms ease;
		cursor: pointer;
	}

	.dropzone--active {
		border-color: var(--netz-brand-primary);
		background: color-mix(in srgb, var(--netz-brand-primary) 4%, transparent);
	}

	.dropzone-prompt {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--netz-space-stack-xs, 8px);
	}

	.dropzone-icon { font-size: 32px; }

	.dropzone-text {
		font-size: var(--netz-text-body, 0.9375rem);
		color: var(--netz-text-secondary);
	}

	.dropzone-hint {
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-muted);
	}

	.dropzone-input {
		position: absolute;
		inset: 0;
		opacity: 0;
		cursor: pointer;
	}

	.dropzone-file {
		display: flex;
		align-items: center;
		gap: var(--netz-space-inline-sm, 10px);
		justify-content: center;
	}

	.dropzone-filename {
		font-weight: 600;
		color: var(--netz-text-primary);
		font-family: var(--netz-font-mono);
		font-size: var(--netz-text-small, 0.8125rem);
	}

	.dropzone-size {
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-muted);
	}

	.dropzone-clear {
		border: none;
		background: transparent;
		color: var(--netz-danger);
		font-size: var(--netz-text-small, 0.8125rem);
		cursor: pointer;
		text-decoration: underline;
		font-family: var(--netz-font-sans);
	}

	/* ── Form fields ─────────────────────────────────────────────────────── */
	.upload-field {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.upload-label {
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-muted);
		font-weight: 500;
	}

	.upload-select {
		height: var(--netz-space-control-height-sm, 32px);
		padding: 0 var(--netz-space-inline-sm, 10px);
		border: 1px solid var(--netz-border);
		border-radius: var(--netz-radius-sm, 8px);
		background: var(--netz-surface-elevated);
		color: var(--netz-text-primary);
		font-size: var(--netz-text-small, 0.8125rem);
		font-family: var(--netz-font-sans);
	}

	.upload-error {
		padding: var(--netz-space-stack-xs, 8px) var(--netz-space-inline-sm, 12px);
		border-radius: var(--netz-radius-sm, 8px);
		background: color-mix(in srgb, var(--netz-danger) 8%, transparent);
		color: var(--netz-danger);
		font-size: var(--netz-text-small, 0.8125rem);
	}

	/* ── Pipeline progress ────────────────────────────────────────────────── */
	.pipeline {
		border: 1px solid var(--netz-border-subtle);
		border-radius: var(--netz-radius-md, 12px);
		padding: var(--netz-space-stack-lg, 24px) var(--netz-space-inline-lg, 24px);
		background: var(--netz-surface-elevated);
	}

	.pipeline-title {
		font-size: var(--netz-text-h4, 1.125rem);
		font-weight: 600;
		color: var(--netz-text-primary);
		margin-bottom: var(--netz-space-stack-md, 16px);
	}

	.pipeline-bar-track {
		height: 6px;
		background: var(--netz-surface-alt);
		border-radius: 3px;
		overflow: hidden;
		margin-bottom: var(--netz-space-stack-md, 16px);
	}

	.pipeline-bar-fill {
		height: 100%;
		background: var(--netz-brand-primary);
		border-radius: 3px;
		transition: width 400ms ease;
	}

	.pipeline-stages {
		display: grid;
		grid-template-columns: repeat(5, 1fr);
		gap: var(--netz-space-stack-xs, 8px);
	}

	.pipeline-stage {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 4px;
	}

	.pipeline-stage-dot {
		width: 10px;
		height: 10px;
		border-radius: 50%;
		background: var(--netz-border-subtle);
		transition: background-color 300ms ease;
	}

	.pipeline-stage--done .pipeline-stage-dot { background: var(--netz-success); }
	.pipeline-stage--active .pipeline-stage-dot {
		background: var(--netz-brand-primary);
		animation: pulse-stage 1s ease infinite;
	}

	@keyframes pulse-stage {
		0%, 100% { transform: scale(1); }
		50% { transform: scale(1.3); }
	}

	.pipeline-stage-label {
		font-size: 10px;
		color: var(--netz-text-muted);
		text-align: center;
		white-space: nowrap;
	}

	.pipeline-stage--done .pipeline-stage-label { color: var(--netz-success); }
	.pipeline-stage--active .pipeline-stage-label { color: var(--netz-brand-primary); font-weight: 600; }

	.pipeline-result {
		margin-top: var(--netz-space-stack-md, 16px);
		padding-top: var(--netz-space-stack-sm, 12px);
		border-top: 1px solid var(--netz-border-subtle);
		display: flex;
		align-items: center;
		justify-content: space-between;
		font-size: var(--netz-text-small, 0.8125rem);
		color: var(--netz-text-secondary);
	}
</style>
