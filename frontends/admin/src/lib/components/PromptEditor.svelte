<!--
  Prompt Editor — CodeMirror Jinja2 editor (left) and live preview (right).
  Explicit Validate and Run Preview controls. Version history with actor and summary.
  Lazy-loaded CodeMirror via JinjaEditor component.
-->
<script lang="ts">
	import { SectionCard, ActionButton, ConfirmDialog, Button } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import DOMPurify from "dompurify";
	import JinjaEditor from "$lib/components/JinjaEditor.svelte";

	/** Sanitize HTML preview via DOMPurify to prevent stored XSS. */
	function sanitizePreview(html: string): string {
		if (typeof window === "undefined") return "";
		return DOMPurify.sanitize(html);
	}

	let {
		vertical,
		templateName,
		token,
	}: {
		vertical: string;
		templateName: string;
		token: string;
	} = $props();

	let content = $state("");
	let preview = $state("");
	let previewErrors = $state<string[]>([]);
	let validationErrors = $state<string[]>([]);
	let validating = $state(false);
	let previewing = $state(false);
	let sourceLevel = $state("filesystem");
	let version = $state<number | null>(null);
	let loading = $state(true);
	let saving = $state(false);
	let saveMessage = $state<string | null>(null);
	let previewDebounceTimer: ReturnType<typeof setTimeout> | null = null;

	// Version history types.
	// actor_id and change_summary are pending backend — they are not in PromptDetailResponse yet.
	type PromptVersionEntry = {
		version: number;
		created_at: string;
		content_preview?: string;
		// TODO: pending backend — actor_id not returned by /versions endpoint
		actor_id?: string | null;
		// TODO: pending backend — change_summary not returned by /versions endpoint
		change_summary?: string | null;
	};

	// Version history state
	let showHistory = $state(false);
	let historyLoading = $state(false);
	let versions = $state<PromptVersionEntry[]>([]);
	let showRevertConfirm = $state(false);
	let revertTarget = $state<number | null>(null);
	let showDeleteConfirm = $state(false);

	const api = createClientApiClient(() => Promise.resolve(token));

	async function loadPrompt() {
		loading = true;
		try {
			const result = await api.get<{
				content: string;
				source_level: string;
				version: number | null;
			}>(`/admin/prompts/${vertical}/${templateName}`);
			content = result.content;
			sourceLevel = result.source_level;
			version = result.version;
			await doPreview();
		} catch {
			content = "";
		} finally {
			loading = false;
		}
	}

	async function doPreview() {
		previewing = true;
		try {
			const result = await api.post<{ rendered: string; errors: string[] }>(
				`/admin/prompts/${vertical}/${templateName}/preview`,
				{ content, sample_data: {} },
			);
			preview = result.rendered;
			previewErrors = result.errors;
		} catch {
			previewErrors = ["Preview request failed"];
		} finally {
			previewing = false;
		}
	}

	async function doValidate() {
		validating = true;
		validationErrors = [];
		try {
			const result = await api.post<{ valid: boolean; errors: string[] }>(
				`/admin/prompts/${vertical}/${templateName}/validate`,
				{ content },
			);
			validationErrors = result.errors;
		} catch {
			validationErrors = ["Validation request failed"];
		} finally {
			validating = false;
		}
	}

	function onEditorChange(newValue: string) {
		content = newValue;
		// Debounced auto-validate on edit (not auto-preview — preview is explicit)
		if (previewDebounceTimer) clearTimeout(previewDebounceTimer);
		previewDebounceTimer = setTimeout(() => {
			void doValidate();
		}, 600);
	}

	async function save() {
		saving = true;
		saveMessage = null;
		try {
			const result = await api.put<{ template_name: string; version: number }>(
				`/admin/prompts/${vertical}/${templateName}`,
				{ content },
			);
			version = result.version;
			sourceLevel = "global";
			saveMessage = `Saved (v${result.version})`;
			setTimeout(() => (saveMessage = null), 3000);
			// Refresh history if visible
			if (showHistory) await loadHistory();
		} catch (e: unknown) {
			saveMessage = e instanceof Error ? e.message : "Save failed";
		} finally {
			saving = false;
		}
	}

	async function revert() {
		showDeleteConfirm = true;
	}

	async function deleteOverride() {
		try {
			await api.delete(`/admin/prompts/${vertical}/${templateName}`);
			await loadPrompt();
		} catch {
			/* loadPrompt will show current state */
		}
	}

	async function loadHistory() {
		historyLoading = true;
		try {
			versions = await api.get<typeof versions>(
				`/admin/prompts/${vertical}/${templateName}/versions`,
			);
		} catch {
			versions = [];
		} finally {
			historyLoading = false;
		}
	}

	function toggleHistory() {
		showHistory = !showHistory;
		if (showHistory && versions.length === 0) {
			void loadHistory();
		}
	}

	function confirmRevert(ver: number) {
		revertTarget = ver;
		showRevertConfirm = true;
	}

	async function doRevertToVersion() {
		if (revertTarget === null) return;
		try {
			await api.post(`/admin/prompts/${vertical}/${templateName}/revert/${revertTarget}`);
			await loadPrompt();
			if (showHistory) await loadHistory();
			saveMessage = `Reverted to v${revertTarget}`;
			setTimeout(() => (saveMessage = null), 3000);
		} catch (e) {
			saveMessage = e instanceof Error ? e.message : "Revert failed";
		}
		revertTarget = null;
	}

	$effect(() => {
		const _v = vertical;
		const _t = templateName;
		void loadPrompt();
	});

	const isReadonly = $derived(sourceLevel === "filesystem");
	const syntaxValid = $derived(validationErrors.length === 0);
</script>

<SectionCard title={templateName}>
	{#if loading}
		<p class="text-sm text-[var(--netz-text-muted)]">Loading template...</p>
	{:else}
		<!-- Header -->
		<div class="mb-3 flex items-center justify-between">
			<div class="flex items-center gap-2">
				<span
					class="h-2 w-2 rounded-full {syntaxValid ? 'bg-green-500' : 'bg-red-500'}"
				></span>
				<span class="text-xs text-[var(--netz-text-muted)]">
					{isReadonly
						? "Viewing filesystem template (read-only)"
						: `Editing ${sourceLevel} override`}
					{#if version}
						&middot; v{version}
					{/if}
				</span>
			</div>
			<div class="flex items-center gap-2">
				{#if saveMessage}
					<span class="text-xs text-[var(--netz-brand-primary)]">{saveMessage}</span>
				{/if}
				<!-- Validate: triggers lint from CodeMirror content via backend validate endpoint -->
				<Button
					variant="outline"
					size="sm"
					onclick={() => void doValidate()}
					disabled={validating || isReadonly}
				>
					{validating ? "Validating…" : "Validate"}
				</Button>
				<!-- Run Preview: calls backend preview endpoint explicitly. Disabled if no preview endpoint -->
				<Button
					variant="outline"
					size="sm"
					onclick={() => void doPreview()}
					disabled={previewing || isReadonly}
					title={isReadonly ? "Preview not available for filesystem templates" : "Run preview with empty sample data"}
				>
					{previewing ? "Running…" : "Run Preview"}
				</Button>
				<Button variant="ghost" size="sm" onclick={toggleHistory}>
					{showHistory ? "Hide History" : "History"}
				</Button>
			</div>
		</div>

		<!-- Version History (lazy-loaded) -->
		{#if showHistory}
			<div class="mb-4 rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface-alt)] p-3">
				<h3 class="mb-2 text-sm font-medium text-[var(--netz-text-primary)]">Version History</h3>
				{#if historyLoading}
					<p class="text-xs text-[var(--netz-text-muted)]">Loading versions...</p>
				{:else if versions.length === 0}
					<p class="text-xs text-[var(--netz-text-muted)]">No version history available.</p>
				{:else}
					<div class="max-h-48 space-y-2 overflow-y-auto">
						{#each versions as ver}
							<div class="flex items-center justify-between rounded border border-[var(--netz-border)] bg-[var(--netz-surface)] px-3 py-2">
								<div class="min-w-0 flex-1">
									<div class="flex items-center gap-2">
										<span class="text-sm font-medium text-[var(--netz-text-primary)]">v{ver.version}</span>
										<span class="text-xs text-[var(--netz-text-muted)]">{ver.created_at}</span>
										{#if ver.actor_id}
											<span class="text-xs text-[var(--netz-text-secondary)]">by {ver.actor_id}</span>
										{/if}
									</div>
									{#if ver.change_summary}
										<p class="mt-0.5 truncate text-xs text-[var(--netz-text-muted)]">{ver.change_summary}</p>
									{/if}
								</div>
								<div class="ml-3 flex-shrink-0">
									{#if ver.version !== version}
										<Button variant="outline" size="sm" onclick={() => confirmRevert(ver.version)}>
											Revert
										</Button>
									{:else}
										<span class="text-xs text-[var(--netz-brand-primary)]">Current</span>
									{/if}
								</div>
							</div>
						{/each}
					</div>
				{/if}
			</div>
		{/if}

		<!-- Split Pane -->
		<div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
			<!-- Left: CodeMirror Jinja2 Editor -->
			<div>
				<label class="mb-1 block text-xs text-[var(--netz-text-muted)]">
					Template (Jinja2)
				</label>
				<JinjaEditor
					bind:value={content}
					readonly={isReadonly}
					ariaLabel="Jinja2 template editor for {templateName}"
					onChange={onEditorChange}
				/>
				{#if validationErrors.length > 0}
					<div class="mt-2 space-y-1">
						{#each validationErrors as err}
							<p class="text-xs text-[var(--netz-danger)]">{err}</p>
						{/each}
					</div>
				{/if}
			</div>

			<!-- Right: Preview -->
			<div>
				<label class="mb-1 block text-xs text-[var(--netz-text-muted)]">Preview</label>
				<div
					class="h-full min-h-[20rem] overflow-auto rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface-alt)] p-3"
				>
					{#if previewErrors.length > 0}
						<div class="space-y-1">
							{#each previewErrors as err}
								<p class="text-xs text-[var(--netz-danger)]">{err}</p>
							{/each}
						</div>
					{:else}
						<div class="prose prose-sm text-[var(--netz-text-primary)]">
							{@html sanitizePreview(preview)}
						</div>
					{/if}
				</div>
			</div>
		</div>

		<!-- Actions -->
		{#if !isReadonly}
			<div class="mt-4 flex justify-between">
				<Button variant="destructive" size="sm" onclick={revert}>
					Revert Override
				</Button>
				<ActionButton onclick={save} loading={saving} loadingText="Saving..." disabled={!syntaxValid}>
					Save for ALL tenants
				</ActionButton>
			</div>
		{/if}
	{/if}
</SectionCard>

<ConfirmDialog
	bind:open={showRevertConfirm}
	title="Revert to Version — affects ALL tenants"
	message="This will revert the {templateName} prompt to version {revertTarget} for ALL tenants. Current content will be overwritten."
	confirmLabel="Revert for ALL tenants"
	confirmVariant="destructive"
	onConfirm={doRevertToVersion}
/>

<ConfirmDialog
	bind:open={showDeleteConfirm}
	title="Remove Override — affects ALL tenants"
	message="This will remove the {templateName} prompt override for {vertical}. All tenants will fall back to the filesystem template. This is a global-impact action."
	confirmLabel="Remove for ALL tenants"
	confirmVariant="destructive"
	onConfirm={deleteOverride}
/>
