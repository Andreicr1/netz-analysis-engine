<!--
  Prompt Editor — split pane with textarea (left) and live preview (right).
  Validates on debounced keystrokes, shows syntax errors inline.
  Includes version history panel (lazy-loaded on tab click).
-->
<script lang="ts">
	import { SectionCard, ActionButton, ConfirmDialog, Button } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import DOMPurify from "dompurify";

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
	let sourceLevel = $state("filesystem");
	let version = $state<number | null>(null);
	let loading = $state(true);
	let saving = $state(false);
	let saveMessage = $state<string | null>(null);
	let previewDebounceTimer: ReturnType<typeof setTimeout> | null = null;

	// Version history state
	let showHistory = $state(false);
	let historyLoading = $state(false);
	let versions = $state<{ version: number; created_at: string; content_preview?: string }[]>([]);
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
		try {
			const result = await api.post<{ rendered: string; errors: string[] }>(
				`/admin/prompts/${vertical}/${templateName}/preview`,
				{ content, sample_data: {} },
			);
			preview = result.rendered;
			previewErrors = result.errors;
		} catch {
			previewErrors = ["Preview request failed"];
		}
	}

	async function doValidate() {
		try {
			const result = await api.post<{ valid: boolean; errors: string[] }>(
				`/admin/prompts/${vertical}/${templateName}/validate`,
				{ content },
			);
			validationErrors = result.errors;
		} catch {
			validationErrors = ["Validation request failed"];
		}
	}

	function onInput(value: string) {
		content = value;
		if (previewDebounceTimer) clearTimeout(previewDebounceTimer);
		previewDebounceTimer = setTimeout(() => {
			void doPreview();
			void doValidate();
		}, 500);
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
								<div>
									<span class="text-sm font-medium text-[var(--netz-text-primary)]">v{ver.version}</span>
									<span class="ml-2 text-xs text-[var(--netz-text-muted)]">{ver.created_at}</span>
								</div>
								{#if ver.version !== version}
									<Button variant="outline" size="sm" onclick={() => confirmRevert(ver.version)}>
										Revert
									</Button>
								{:else}
									<span class="text-xs text-[var(--netz-brand-primary)]">Current</span>
								{/if}
							</div>
						{/each}
					</div>
				{/if}
			</div>
		{/if}

		<!-- Split Pane -->
		<div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
			<!-- Left: Editor -->
			<div>
				<label class="mb-1 block text-xs text-[var(--netz-text-muted)]">
					Template (Jinja2)
				</label>
				<textarea
					value={content}
					oninput={(e) => onInput(e.currentTarget.value)}
					readonly={isReadonly}
					rows={20}
					class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] p-3 font-mono text-xs text-[var(--netz-text-primary)] focus:border-[var(--netz-brand-primary)] focus:outline-none {isReadonly
						? 'opacity-60'
						: ''}"
					spellcheck="false"
				></textarea>
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
					Save
				</ActionButton>
			</div>
		{/if}
	{/if}
</SectionCard>

<ConfirmDialog
	bind:open={showRevertConfirm}
	title="Revert to Version"
	message="This will revert the prompt to version {revertTarget}. Current content will be overwritten."
	confirmLabel="Revert"
	confirmVariant="destructive"
	onConfirm={doRevertToVersion}
/>

<ConfirmDialog
	bind:open={showDeleteConfirm}
	title="Remove Override"
	message="This will remove the override. The prompt will fall back to the next cascade level."
	confirmLabel="Remove"
	confirmVariant="destructive"
	onConfirm={deleteOverride}
/>
